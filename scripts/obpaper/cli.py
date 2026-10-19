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


async def download_one(ctx, engine, url, title, root):
    from pypdf import PdfReader
    temporary = root / ('.paper-' + uuid.uuid4().hex + '.part')
    title, doi, links = title, doi_from(url), []
    try:
        # A direct PDF URL may not be navigable in headful Edge. Fetch it
        # through the same browser context first, without OS proxy settings.
        try:
            response = await ctx.request.get(url, timeout=90000)
            content = await response.body() if response.ok else b''
            await response.dispose()
        except Exception:
            # Browser navigation can pass publisher checks that block API requests.
            content = b''
        if content.startswith(b'%PDF-'):
            temporary.write_bytes(content)
        else:
            page = await ctx.new_page()
            await page.goto(url, wait_until='domcontentloaded', timeout=90000)
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
            engine.RUN_CTX.update(events_path=None, manual_pages=[],
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
        pdf = root / (name + '.pdf')
        if pdf.exists():
            if pdf.read_bytes() != temporary.read_bytes():
                raise ValueError('已有同名 PDF 内容不同，未覆盖；请指定另一个输出目录')
        else:
            temporary.replace(pdf)
        print(f'PDF: {pdf}')
        return pdf, title
    finally:
        temporary.unlink(missing_ok=True)


async def run(args):
    from playwright.async_api import async_playwright
    from .convert import convert
    from .mineru import MinerUError
    engine = load_engine()
    PROFILE.mkdir(parents=True, exist_ok=True)
    root = Path(args.output).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    failures = 0
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(PROFILE), channel='msedge', headless=False, accept_downloads=True,
            args=['--profile-directory=Default', '--no-proxy-server'], viewport={'width': 1280, 'height': 900})
        try:
            if args.prepare_profile:
                page = await ctx.new_page()
                await page.goto(args.urls[0] if args.urls else 'https://doi.org', wait_until='domcontentloaded')
                await asyncio.to_thread(input, '在专用 Edge 中确认校园访问或登录完成后，回到此处按回车关闭：')
                return 0
            for index, url in enumerate(args.urls):
                try:
                    title = args.title[index] if args.title else None
                    pdf, title = await download_one(ctx, engine, url, title, root)
                    if not args.pdf_only:
                        markdown = await asyncio.to_thread(convert, pdf, title, Path(args.mineru_config),
                                                           keep_pdf=args.keep_pdf)
                        print(f'Markdown: {markdown}')
                except Exception as exc:
                    failures += 1
                    report_error(exc, index + 1)
                    if isinstance(exc, MinerUError) and exc.stop:
                        break
                finally:
                    for page in list(ctx.pages):
                        await page.close()
        finally:
            await ctx.close()
    return 2 if failures else 0


def confirm_campus(*, confirmed=False):
    # Copied from AutoPaper edge_download.py; only project/status labels adapted.
    print('请退出 Clash（包括 TUN 模式），关闭 Obsidian Papers 专用 Edge 窗口。')
    print('断开代理后，本脚本仍会独立运行；每篇完成后会自动保存结果。')
    if confirmed:
        return True
    try:
        answer = input('确认已经完成上述操作，并允许专用 Edge 开始下载？输入 YES 后回车：')
    except EOFError:
        print('等待用户确认关闭代理，尚未打开浏览器或开始下载。')
        return False
    if answer.strip().upper() != 'YES':
        print('未开始下载。')
        return False
    return True


def report_error(exc, index=None):
    from .mineru import MinerUError
    message = str(exc) if isinstance(exc, (ValueError, FileNotFoundError, MinerUError)) else (
        f'操作失败（{type(exc).__name__}），已下载 PDF 和未完成任务进度已保留。')
    print((f'第 {index} 篇：' if index else '') + message, file=sys.stderr)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='校园网下载论文 PDF 并默认转换 Markdown')
    parser.add_argument('urls', nargs='*', help='一个或多个论文链接')
    parser.add_argument('--title', action='append', help='按链接顺序重复指定准确论文标题')
    parser.add_argument('--output', default=str(ROOT / 'downloads'), help='文件直接保存到此目录，不按论文建子目录')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--pdf-only', action='store_true', help='仅下载 PDF，不转换或请求 token')
    mode.add_argument('--markdown', action='store_true', help='兼容旧入口；转换已是默认行为')
    parser.add_argument('--keep-pdf', action='store_true', help='转换成功后保留 PDF；默认成功后删除，失败时保留')
    parser.add_argument('--mineru-config', default=str(ROOT / 'config/mineru.local.toml'))
    parser.add_argument('--configure-mineru', action='store_true', help='隐藏输入 token 并保存到私人配置')
    parser.add_argument('--prepare-profile', action='store_true')
    parser.add_argument('--campus-confirmed', action='store_true', help='仅在用户已明确确认退出 Clash/TUN 并关闭专用 Edge 后使用')
    parser.add_argument('--dry-run', action='store_true', help='仅检查参数，不联网、请求 token 或打开浏览器')
    parser.add_argument('--convert-pdf', type=Path, help='只转换已有 PDF；需 --title')
    args = parser.parse_args(argv)
    try:
        from .configuration import ensure_token
        args.output = str(Path(args.output).expanduser().resolve())
        args.mineru_config = str(Path(args.mineru_config).expanduser().resolve())
        if args.configure_mineru:
            ensure_token(Path(args.mineru_config), configure=True)
            return 0
        if args.convert_pdf:
            if not args.title or len(args.title) != 1 or args.urls or args.pdf_only:
                parser.error('--convert-pdf requires one --title and no URLs or --pdf-only')
            if args.dry_run:
                print(args.convert_pdf.resolve().with_name(title_filename(args.title[0]) + '.md'))
                return 0
            ensure_token(Path(args.mineru_config))
            from .convert import convert
            print(convert(args.convert_pdf.resolve(), args.title[0], Path(args.mineru_config),
                          keep_pdf=args.keep_pdf))
            return 0
        if not args.prepare_profile and not args.urls:
            parser.error('Provide one or more paper URLs')
        if args.title and len(args.title) != len(args.urls):
            parser.error('Repeat --title once per URL, or omit it to use paper metadata')
        for url in args.urls:
            if urlparse(url).scheme not in {'https', 'http'} or not urlparse(url).netloc:
                parser.error('Provide HTTP(S) paper URLs')
        if args.dry_run:
            print(json.dumps(dict(urls=args.urls, output=args.output,
                                  filenames=[title_filename(t) + '.pdf' for t in (args.title or [])],
                                  markdown=not args.pdf_only,
                                  keep_pdf=args.keep_pdf or args.pdf_only), ensure_ascii=False))
            return 0
        if not args.pdf_only and not args.prepare_profile:
            ensure_token(Path(args.mineru_config))
        if not confirm_campus(confirmed=args.campus_confirmed):
            return 0
        os.chdir(ROOT)
        for key in list(os.environ):
            if key.lower() in {'http_proxy', 'https_proxy', 'all_proxy'}:
                os.environ.pop(key, None)
        return asyncio.run(run(args))
    except Exception as exc:
        report_error(exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
