import argparse
import asyncio
from io import BytesIO
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlparse
import uuid

from .naming import title_filename
from .validation import validate_pdf
from .edge import fetch_main_pdf

ROOT = Path(__file__).resolve().parents[2]
ENGINE_COMMIT = '1cc667351875410197acf4471e667ac272a0092e'
PROFILE = ROOT / 'browser_profiles/edge-obsidian-papers'


def load_engine():
    engine_root = ROOT / '_references/ref-downloader'
    revision = subprocess.check_output(['git', '-C', str(engine_root), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != ENGINE_COMMIT:
        raise ValueError('Unexpected download engine revision; run scripts/setup.ps1')
    engine_file = engine_root / 'skills/ref-downloader/scripts/download_refs.py'
    os.environ['REF_DOWNLOADER_CONFIG'] = str(ROOT / 'config/ref_downloader_edge.toml')
    os.environ['REF_DOWNLOADER_BROWSER'] = 'edge'
    sys.path.insert(0, str(engine_file.parent))
    spec = importlib.util.spec_from_file_location('obpaper_ref_engine', engine_file)
    engine = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = engine
    spec.loader.exec_module(engine)
    cfg = engine.load_config()
    engine.init_institution_config(cfg.institution)
    engine.init_user_config(cfg.user)
    return engine


def doi_from(value):
    match = re.search(r'10\.\d{4,9}/[^\s?#"<>]+', unquote(value), re.I)
    return match.group(0).rstrip('.,;') if match else ''


async def run(args):
    from playwright.async_api import async_playwright
    from pypdf import PdfReader
    from .convert import convert
    engine = load_engine()
    PROFILE.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(PROFILE), channel='msedge', headless=False, accept_downloads=True,
            args=['--no-proxy-server'], viewport={'width': 1280, 'height': 900})
        try:
            if args.prepare_profile:
                page = await ctx.new_page()
                await page.goto(args.url or 'https://doi.org', wait_until='domcontentloaded')
                await asyncio.to_thread(input, '在专用 Edge 中确认校园访问或登录完成后，回到此处按回车关闭：')
                return
            root = Path(args.output).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            temporary = root / ('.paper-' + uuid.uuid4().hex + '.part')
            title, doi, links = args.title, doi_from(args.url), []
            try:
                # A direct PDF URL may not be navigable in headful Edge. Fetch it
                # through the same browser context first, without OS proxy settings.
                try:
                    response = await ctx.request.get(args.url, timeout=90000)
                    content = await response.body() if response.ok else b''
                    await response.dispose()
                except Exception:
                    # Browser navigation can pass publisher checks that block API requests.
                    content = b''
                if content.startswith(b'%PDF-'):
                    temporary.write_bytes(content)
                else:
                    page = await ctx.new_page()
                    await page.goto(args.url, wait_until='domcontentloaded', timeout=90000)
                    metadata = await page.evaluate('''() => {
                        const meta = n => document.querySelector(`meta[name="${n}"],meta[property="${n}"]`)?.content || '';
                        return {title: meta('citation_title') || meta('dc.title') || meta('og:title'),
                            doi: meta('citation_doi') || meta('dc.identifier'),
                            links: [...document.querySelectorAll('meta[name="citation_pdf_url"],a[href]')]
                                .map(e => e.content || e.href).filter(u => /\\.pdf(?:[?#]|$)|\\/pdfft|\\/epdf\\//i.test(u))};
                    }''')
                    title = title or metadata['title']
                    doi = doi_from(metadata['doi']) or doi_from(page.url) or doi
                    links = metadata['links'][:10]
                    await page.close()
                    engine.RUN_CTX.update(events_path=root / 'edge-events.jsonl', manual_pages=[],
                                          current_ref=dict(id=1, label='paper', doi=doi, title=title or 'paper'))
                    if doi:
                        try:
                            await asyncio.wait_for(fetch_main_pdf(engine, ctx, dict(doi=doi), temporary), 600)
                        except (engine.ManualInterventionRequired, asyncio.TimeoutError):
                            pass
                    if not temporary.exists() or not validate_pdf(temporary, 10000)[0]:
                        for link in links:
                            result = await ctx.request.get(link, timeout=90000)
                            data = await result.body() if result.ok else b''
                            await result.dispose()
                            if data.startswith(b'%PDF-'):
                                temporary.write_bytes(data)
                                break
                if not temporary.exists() or not validate_pdf(temporary, 10000)[0]:
                    raise ValueError('未下载到有效 PDF；请检查校园权限，或使用 --prepare-profile 完成登录后重试')
                if not title:
                    reader = PdfReader(BytesIO(temporary.read_bytes()))
                    title = reader.metadata.title if reader.metadata else None
                if not title or not str(title).strip():
                    raise ValueError('无法可靠取得论文标题；请传入 --title 后重试')
                title = str(title).strip()
                name = title_filename(title)
                # Title collisions must never silently reuse an unrelated paper.
                folder = root / name
                record = dict(title=title, url=args.url, doi=doi)
                manifest = folder / 'paper.json'
                if folder.exists():
                    old = json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
                    if old != record:
                        raise ValueError('同名目录已存在且来源不同；请指定另一个 --output 目录')
                folder.mkdir(exist_ok=True)
                pdf = folder / (name + '.pdf')
                if pdf.exists():
                    if pdf.read_bytes() != temporary.read_bytes():
                        raise ValueError('已有同名 PDF 内容不同，未覆盖；请指定另一个输出目录')
                else:
                    temporary.replace(pdf)
                manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
                print(f'PDF: {pdf}')
            finally:
                temporary.unlink(missing_ok=True)
        finally:
            await ctx.close()
    if args.markdown:
        markdown = await asyncio.to_thread(convert, pdf, title, Path(args.mineru_config).resolve())
        print(f'Markdown: {markdown}')


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='从论文链接下载校园网 PDF，可选 MinerU 转 Markdown')
    parser.add_argument('url', nargs='?')
    parser.add_argument('--title', help='页面或 PDF 无可靠标题时手动指定论文标题')
    parser.add_argument('--output', default=str(ROOT / 'downloads'), help='Obsidian vault 内的目标目录')
    parser.add_argument('--markdown', action='store_true', help='将论文上传至 MinerU 并转换')
    parser.add_argument('--mineru-config', default=str(ROOT / 'config/mineru.local.toml'))
    parser.add_argument('--prepare-profile', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='仅检查参数，不联网或打开浏览器')
    parser.add_argument('--convert-pdf', type=Path, help='转换已有 PDF，无需再次下载；需 --title')
    args = parser.parse_args(argv)
    try:
        if args.convert_pdf:
            if not args.title:
                parser.error('--convert-pdf requires --title')
            if args.dry_run:
                print(args.convert_pdf.resolve().with_name(title_filename(args.title) + '.md'))
                return 0
            from .convert import convert
            print(convert(args.convert_pdf.resolve(), args.title, Path(args.mineru_config).resolve()))
            return 0
        if not args.prepare_profile and not args.url:
            parser.error('Provide a paper URL')
        if args.url and (urlparse(args.url).scheme not in {'https', 'http'} or not urlparse(args.url).netloc):
            parser.error('Provide an HTTP(S) paper URL')
        if args.dry_run:
            print(json.dumps(dict(url=args.url, output=str(Path(args.output).resolve()),
                                  filename=title_filename(args.title) + '.pdf' if args.title else '由论文标题生成',
                                  markdown=args.markdown), ensure_ascii=False))
            return 0
        args.output = str(Path(args.output).expanduser().resolve())
        args.mineru_config = str(Path(args.mineru_config).expanduser().resolve())
        os.chdir(ROOT)
        for key in list(os.environ):
            if key.lower() in {'http_proxy', 'https_proxy', 'all_proxy'}:
                os.environ.pop(key, None)
        asyncio.run(run(args))
        return 0
    except Exception as exc:
        from .mineru import MinerUError
        # Network exceptions can include signed links or credentials.
        print(str(exc) if isinstance(exc, (ValueError, FileNotFoundError, MinerUError)) else
              f'操作失败（{type(exc).__name__}），本地文件和转换进度已保留。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
