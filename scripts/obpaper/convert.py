"""Small file-based checkpoint wrapper around AutoPaper's MinerU client."""
import hashlib
import json
import os
from pathlib import Path
import time
from dataclasses import replace

from .mineru import Client, MinerUError, load_settings, extract_result, staging_directory, conversion_lock
from .naming import title_filename
from .validation import validate_pdf


def save_state(path, state):
    temporary = path.with_suffix(path.suffix + '.part')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def convert(pdf: Path, title: str, config: Path) -> Path:
    with conversion_lock(pdf):
        return _convert(pdf, title, config)


def _convert(pdf: Path, title: str, config: Path) -> Path:
    if not validate_pdf(pdf, 1024)[0] or pdf.stat().st_size > 200 * 1024 * 1024:
        raise ValueError('Input must be a valid PDF no larger than 200 MB')
    settings = load_settings(config)
    settings = replace(settings, token=os.environ.get('MINERU_TOKEN') or settings.token)
    if not settings.token:
        raise ValueError('Set MINERU_TOKEN or the token in your private MinerU config')
    with pdf.open('rb') as handle:
        fingerprint = hashlib.file_digest(handle, 'sha256').hexdigest()
    options = dict(settings.options(), is_ocr=settings.ocr)
    checkpoint = pdf.with_suffix('.mineru.json')
    state = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {}
    identity = dict(sha256=fingerprint, options=options, title=title)
    if state and any(state.get(k) != v for k, v in identity.items()):
        raise ValueError('PDF, title or parser options changed; use a separate output folder')
    output = pdf.parent / 'markdown'
    if state.get('markdown'):
        existing = Path(state['markdown'])
        if existing.is_file():
            return existing
        raise ValueError('Saved Markdown is missing; restore it or use a separate output folder')
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
                raise MinerUError('MinerU task failed; check the dashboard; checkpoint retained')
            if result.get('state') == 'done':
                if not result.get('full_zip_url'):
                    raise MinerUError('Completed task lacks a result ZIP URL')
                with staging_directory(pdf.parent) as staging:
                    archive = staging / 'result.zip'
                    client.download(result['full_zip_url'], archive)
                    extracted = staging / 'extracted'
                    markdown = extract_result(archive, extracted)
                    named = markdown.with_name(title_filename(title) + '.md')
                    if named != markdown and named.exists():
                        raise MinerUError('Title conflicts with another file in the result')
                    markdown.rename(named)
                    # Keep Markdown beside its original relative image directories.
                    relative = named.relative_to(extracted)
                    if output.exists():
                        existing = output / relative
                        if not existing.is_file() or existing.read_bytes() != named.read_bytes():
                            raise MinerUError('Existing Markdown differs; refusing to overwrite')
                    else:
                        extracted.rename(output)
                    state['markdown'] = str(output / relative)
                    save_state(checkpoint, state)
                    return output / relative
            time.sleep(min(settings.poll_seconds, max(0, deadline - time.monotonic())))
        raise MinerUError('Timed out; rerun the same command to resume the saved task')
    finally:
        client.close()
