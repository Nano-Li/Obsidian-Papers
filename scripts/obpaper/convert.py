"""Small file-based checkpoint wrapper around AutoPaper's MinerU client."""
import hashlib
import json
import os
from pathlib import Path
import time
from dataclasses import replace

from .mineru import Client, MinerUError, load_settings, extract_result, staging_directory, conversion_lock
from .naming import title_filename, _extract_title_from_layout
from .validation import validate_pdf
from .export import flatten_result


def checkpoint_path(pdf: Path, config: Path) -> Path:
    key = hashlib.sha256(str(pdf.resolve()).encode('utf-8')).hexdigest()
    folder = config.resolve().parent / '.state'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (key + '.mineru.json')


def save_state(path, state):
    temporary = path.with_suffix(path.suffix + '.part')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def convert(pdf: Path, title: str, config: Path, *, keep_pdf: bool = False, output_dir: Path | None = None) -> Path:
    checkpoint = checkpoint_path(pdf, config)
    with conversion_lock(checkpoint):
        return _convert(pdf, title, config, checkpoint, keep_pdf=keep_pdf, output_dir=output_dir)


def _convert(pdf: Path, title: str, config: Path, checkpoint: Path, *, keep_pdf: bool, output_dir: Path | None) -> Path:
    if not validate_pdf(pdf, 1024)[0] or pdf.stat().st_size > 200 * 1024 * 1024:
        raise ValueError('Input must be a valid PDF no larger than 200 MB')
    settings = load_settings(config)
    settings = replace(settings, token=(os.environ.get('MINERU_TOKEN') or settings.token).strip())
    if not settings.token:
        raise ValueError('Set MINERU_TOKEN or the token in your private MinerU config')
    with pdf.open('rb') as handle:
        fingerprint = hashlib.file_digest(handle, 'sha256').hexdigest()
    options = dict(settings.options(), is_ocr=settings.ocr)
    state = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {}
    identity = dict(sha256=fingerprint, options=options, title=title)
    if state and any(state.get(k) != v for k, v in identity.items()):
        raise ValueError('PDF, title or parser options changed; use a separate output folder')
    output = Path(output_dir).resolve() if output_dir is not None else pdf.parent
    output.mkdir(parents=True, exist_ok=True)
    if not state and (output / (title_filename(title) + '.md')).exists():
        raise ValueError('同名 Markdown 已存在，未创建新的 MinerU 任务；请检查现有笔记')
    state.update(identity)
    client = Client(settings)
    try:
        if not state.get('batch_id'):
            batch, upload = client.submit('paper-' + fingerprint[:16])
            state.update(batch_id=batch, upload_url=upload, uploaded=False)
            save_state(checkpoint, state)
        if not state.get('uploaded'):
            remote = client.result(state['batch_id'])
            if remote.get('state', 'waiting-file') == 'waiting-file':
                client.upload(state['upload_url'], pdf)
            state.update(uploaded=True)
            state.pop('upload_url', None)
            save_state(checkpoint, state)
        deadline = time.monotonic() + settings.timeout_seconds
        while time.monotonic() < deadline:
            result = client.result(state['batch_id'])
            if result.get('state') == 'failed':
                raise MinerUError('MinerU task failed; check the dashboard; checkpoint retained', stop=True)
            if result.get('state') == 'done':
                if not result.get('full_zip_url'):
                    raise MinerUError('Completed task lacks a result ZIP URL')
                with staging_directory(pdf.parent) as staging:
                    archive = staging / 'result.zip'
                    client.download(result['full_zip_url'], archive)
                    extracted = staging / 'extracted'
                    markdown = extract_result(archive, extracted)
                    # Use minerU-kit's first-page title extraction before cleanup.
                    extracted_title = _extract_title_from_layout(markdown.parent / 'layout.json')
                    result_path = flatten_result(extracted, markdown, output, extracted_title or title)
                # Staging (ZIP, JSON and other artifacts) is gone before returning.
                if not keep_pdf:
                    # Only remove this successfully converted source, never a PDF
                    # replaced or edited while the remote conversion was running.
                    with pdf.open('rb') as handle:
                        current = hashlib.file_digest(handle, 'sha256').hexdigest()
                    if current != fingerprint:
                        raise MinerUError('Markdown saved, but source PDF changed; PDF retained')
                    pdf.unlink()
                    print(f'已删除转换成功的 PDF: {pdf}')
                checkpoint.unlink(missing_ok=True)
                return result_path
            time.sleep(min(settings.poll_seconds, max(0, deadline - time.monotonic())))
        raise MinerUError('Timed out; rerun the same command to resume the saved task')
    finally:
        client.close()
