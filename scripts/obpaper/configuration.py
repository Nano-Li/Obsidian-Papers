"""Private MinerU configuration onboarding; never echo or accept a CLI token."""
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import sys

from .mineru import load_settings

ROOT = Path(__file__).resolve().parents[2]


def ensure_token(path: Path, *, configure=False):
    path = path.expanduser().resolve()
    if not path.name.endswith('.local.toml'):
        raise ValueError('私人配置必须使用 .local.toml 文件，不能将 token 写入公开模板')
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'config/mineru.example.toml', path)
    settings = load_settings(path)
    if not configure and (os.environ.get('MINERU_TOKEN', '').strip() or settings.token.strip()):
        return
    print('首次使用 Markdown 转换需要 MinerU token；PDF 将上传至 MinerU。')
    print(f'请提供 token 并保存到本地私人配置（不会上传 Git）：{path}')
    if not sys.stdin.isatty():
        raise ValueError('缺少 MinerU token。请在交互终端运行 --configure-mineru，或填写 config/mineru.local.toml 后继续。')
    token = getpass.getpass('MinerU token（隐藏输入；留空取消）：').strip()
    if not token:
        raise ValueError('未提供 MinerU token，尚未开始下载或转换')
    if any(char.isspace() for char in token):
        raise ValueError('Token 不能包含空白字符')
    save_token(path, token)
    print('MinerU token 已保存到本地私人配置。')


def save_token(path: Path, token: str):
    """Replace only [mineru].token, preserving the rest of the private config."""
    if not path.name.endswith('.local.toml'):
        raise ValueError('私人配置必须使用 .local.toml 文件，不能将 token 写入公开模板')
    text = path.read_text(encoding='utf-8')
    section = re.search(r'(?ms)^\[mineru\][^\S\n]*\n(.*?)(?=^\[|\Z)', text)
    if not section:
        raise ValueError('私人配置缺少 [mineru] 段')
    body = section.group(1)
    line = 'token = ' + json.dumps(token, ensure_ascii=True)
    body, count = re.subn(r'(?m)^token\s*=.*$', lambda _: line, body, count=1)
    if not count:
        body = line + '\n' + body
    updated = text[:section.start(1)] + body + text[section.end(1):]
    temporary = path.with_suffix(path.suffix + '.part')
    temporary.write_text(updated, encoding='utf-8')
    temporary.replace(path)
