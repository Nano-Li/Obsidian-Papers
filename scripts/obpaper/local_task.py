"""Independent Windows entry, adapted from AutoPaper download_approved.bat.

Prepare while Codex is online; confirm and execute in a separate local console.
Task files contain arguments and paths, never the MinerU token itself.
"""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]


def write_status(folder: Path, phase: str, exit_code=None):
    labels = {
        'prepared': '已准备，尚未开始。打开 start.bat，在本地窗口确认。',
        'waiting_for_confirmation': '等待本地窗口输入 YES，不需要回复 Codex。',
        'running': '正在本地执行，不依赖 Codex 在线。',
        'awaiting_model': '本地下载结束。请恢复代理，让 Codex 检查暂存文件并继续转换、命名、归档和清理。',
        'completed': '恢复连接后的整理已完成。',
        'failed': '任务未全部完成。恢复代理后让 Codex 检查 task.log；不要盲目重跑。',
        'cancelled': '已取消，未开始下载。',
    }
    text = ('# Obsidian Papers 本地任务\n\n' + labels[phase] + '\n\n'
            + f'状态：`{phase}`\n\n'
            + (f'退出码：`{exit_code}`\n\n' if exit_code is not None else '')
            + f'更新时间：{datetime.now(timezone.utc).isoformat()}\n\n'
            + '运行记录：[task.log](task.log)\n')
    temporary = folder / 'STATUS.md.part'
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(folder / 'STATUS.md')


def prepare_task(args, *, task_root=None) -> Path:
    folder = (task_root or ROOT / 'config/.state/tasks') / uuid.uuid4().hex
    folder.mkdir(parents=True)
    argv = list(args.urls) + ['--output', str(Path(args.output).resolve()),
                             '--mineru-config', str(Path(args.mineru_config).resolve())]
    for title in args.title or []:
        argv += ['--title', title]
    for flag in ('pdf_only', 'keep_pdf', 'prepare_profile'):
        if getattr(args, flag):
            argv.append('--' + flag.replace('_', '-'))
    (folder / 'task.json').write_text(json.dumps({
        'argv': argv, 'output': str(Path(args.output).resolve()),
        'mineru_config': str(Path(args.mineru_config).resolve()),
        'pdf_only': args.pdf_only, 'keep_pdf': args.keep_pdf, 'prepare_profile': args.prepare_profile,
        'total': len(args.urls),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    # Follow AutoPaper's cd / python / exit-code / pause layout. Pass URLs only
    # through JSON, never interpolate user links or titles into cmd.exe code.
    project = str(ROOT).replace('%', '%%')
    python = str(Path(sys.executable).resolve()).replace('%', '%%')
    launcher = ('@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\n'
                + 'title Obsidian Papers - local task\r\n'
                + f'cd /d "{project}"\r\n'
                + f'"{python}" -X utf8 -m obpaper.local_task "%~dp0task.json"\r\n'
                + 'set "OBPAPER_TASK_EXIT=%ERRORLEVEL%"\r\n'
                + 'echo.\r\necho Task finished. See STATUS.md and task.log beside this file.\r\n'
                + 'pause\r\nexit /b %OBPAPER_TASK_EXIT%\r\n')
    with (folder / 'start.bat').open('w', encoding='utf-8', newline='') as handle:
        handle.write(launcher)
    write_status(folder, 'prepared')
    return folder


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, value):
        self.console.write(value)
        self.log.write(value)
        self.flush()
        return len(value)

    def flush(self):
        self.console.flush()
        self.log.flush()

    def isatty(self):
        return self.console.isatty()


def execute_task(path: Path) -> int:
    from .cli import main
    path = path.resolve()
    argv = json.loads(path.read_text(encoding='utf-8'))['argv']
    if not isinstance(argv, list) or not all(isinstance(value, str) for value in argv):
        raise ValueError('Invalid local task arguments')
    forbidden = {'--prepare-task', '--finish-task', '--convert-pdf', '--configure-mineru', '--campus-confirmed', '--dry-run'}
    if any(value.split('=', 1)[0] in forbidden for value in argv):
        raise ValueError('Local task must use its own interactive campus confirmation')
    phase = 'prepared'

    def progress(value, **details):
        nonlocal phase
        if value == 'downloaded':
            records_path = path.parent / 'downloads.json'
            records = json.loads(records_path.read_text(encoding='utf-8')) if records_path.exists() else []
            with Path(details['pdf']).open('rb') as handle:
                details['sha256'] = hashlib.file_digest(handle, 'sha256').hexdigest()
            records.append(details)
            records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
            return
        phase = value
        write_status(path.parent, value)

    with (path.parent / 'task.log').open('a', encoding='utf-8') as log:
        with redirect_stdout(Tee(sys.stdout, log)), redirect_stderr(Tee(sys.stderr, log)):
            print('关闭 Clash 后 Codex 可能断线；请在此本地窗口输入 YES，无需回复 Codex。')
            print('本窗口只下载原始 PDF，不做知识库文件的重命名、转换或删除。恢复代理后由模型接着处理。')
            try:
                code = main(argv, progress=progress, task_folder=path.parent)
            except KeyboardInterrupt:
                code = 130
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
            except Exception as exc:
                # Keep exception strings (potentially containing signed URLs) out of logs.
                print(f'本地任务异常：{type(exc).__name__}')
                code = 1
    final = 'cancelled' if phase == 'cancelled' else ('awaiting_model' if code == 0 else 'failed')
    write_status(path.parent, final, code)
    return code


def finish_task(folder: Path, *, dry_run=False):
    """Invoked by the model only after reconnection; never run by start.bat."""
    from .convert import convert
    from .naming import title_filename
    folder = folder.resolve()
    task = json.loads((folder / 'task.json').read_text(encoding='utf-8'))
    path = folder / 'downloads.json'
    if not path.is_file():
        raise ValueError('暂无下载记录，请先检查 STATUS.md 和 task.log')
    records = json.loads(path.read_text(encoding='utf-8'))
    output = Path(task['output'])
    if not output.is_absolute():
        raise ValueError('目标目录必须是已核实的绝对路径')
    plan = []
    for record in records:
        if record.get('finished'):
            continue
        pdf = Path(record['pdf']).resolve()
        if not pdf.is_relative_to(folder / 'raw') or pdf.name != 'source.pdf':
            raise ValueError('暂存文件超出任务目录，未执行任何文件操作')
        if record['title'] == '待核对标题':
            raise ValueError('请由模型核实论文标题并更新 downloads.json 后再整理')
        with pdf.open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').hexdigest() != record['sha256']:
                raise ValueError('暂存 PDF 已变化，请先核查，不继续删除或命名')
        if task['pdf_only'] or task['keep_pdf']:
            target = output / (title_filename(record['title']) + '.pdf')
            if target.exists() and target.read_bytes() != pdf.read_bytes():
                raise ValueError('知识库已有不同内容的同名 PDF，未覆盖，暂存文件已保留')
        plan.append({'source': str(pdf), 'title': record['title'], 'output': str(output),
                     'convert': not task['pdf_only'], 'keep_pdf': task['pdf_only'] or task['keep_pdf']})
    if dry_run:
        return plan
    for record in records:
        if record.get('finished'):
            continue
        pdf = Path(record['pdf']).resolve()
        output.mkdir(parents=True, exist_ok=True)
        markdown = None
        if not task['pdf_only']:
            markdown = convert(pdf, record['title'], Path(task['mineru_config']),
                               keep_pdf=task['keep_pdf'], output_dir=output)
        if task['pdf_only'] or task['keep_pdf']:
            with pdf.open('rb') as handle:
                if hashlib.file_digest(handle, 'sha256').hexdigest() != record['sha256']:
                    raise ValueError('暂存 PDF 已变化，未移动或删除，请由模型检查')
            target = output / (title_filename(record['title']) + '.pdf')
            if target.exists() and target.read_bytes() != pdf.read_bytes():
                raise ValueError('知识库已有不同内容的同名 PDF，未覆盖，暂存文件已保留')
            if not target.exists():
                with target.open('xb') as dest, pdf.open('rb') as source:
                    shutil.copyfileobj(source, dest)
            pdf.unlink()
            record['pdf_output'] = str(target)
        record.update(finished=True, markdown=str(markdown) if markdown else None)
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        # Remove only this now-empty, verified task directory after model review.
        if not any(pdf.parent.iterdir()):
            pdf.parent.rmdir()
    complete = len(records) == task['total'] and all(item.get('finished') for item in records)
    write_status(folder, 'completed' if complete else 'failed', 0 if complete else 2)
    return records


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(execute_task(Path(sys.argv[1])))
