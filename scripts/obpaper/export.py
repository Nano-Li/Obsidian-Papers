"""Flat export adapted from minerU-kit move_llm_minerU.py / batch_run.py.

Keep only the named Markdown and shared images; staging cleanup owns all JSON,
ZIP and parser artifacts. Check image contents before reusing an existing name.
"""
import hashlib
from pathlib import Path
import re
import shutil
from urllib.parse import quote, unquote, urlsplit

from .mineru import MinerUError
from .naming import title_filename

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp', '.tif', '.tiff', '.avif'}


def flatten_result(extracted: Path, markdown: Path, output: Path, title: str) -> Path:
    output = output.resolve()
    destination = output / (title_filename(title) + '.md')
    images = {}
    planned = {}
    for source in sorted(extracted.rglob('*')):
        if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        target = output / 'images' / source.name
        # Shared images from existing papers must never be silently replaced.
        if ((target.exists() and target.read_bytes() != content)
                or (target in planned and planned[target] != digest)):
            target = output / 'images' / (source.stem[:120] + '-' + digest + source.suffix)
        if target.exists() and target.read_bytes() != content:
            raise MinerUError('Existing image conflicts with the parsed result')
        planned[target] = digest
        images[source.resolve()] = target

    def rewrite(value):
        bracketed = value.startswith('<') and value.endswith('>')
        raw = value[1:-1] if bracketed else value
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc:
            return value
        source = (markdown.parent / unquote(parsed.path)).resolve()
        target = images.get(source)
        if target is None:
            return value
        result = quote(target.relative_to(output).as_posix(), safe='/')
        if parsed.fragment:
            result += '#' + parsed.fragment
        return '<' + result + '>' if bracketed else result

    text = markdown.read_text(encoding='utf-8-sig')
    text = re.sub(r'(!?\[[^\]]*\]\(\s*)(<[^>]+>|[^\s)]+)',
                  lambda m: m[1] + rewrite(m[2]), text)
    text = re.sub(r'(?m)^(\s*\[[^\]]+\]:\s*)(<[^>]+>|\S+)',
                  lambda m: m[1] + rewrite(m[2]), text)
    text = re.sub(r'((?:src|href)=["\'])([^"\']+)(["\'])',
                  lambda m: m[1] + rewrite(m[2]) + m[3], text)
    text = re.sub(r'!\[\[([^\]|]+)([^\]]*)\]\]',
                  lambda m: '![[' + unquote(rewrite(m[1])) + m[2] + ']]', text)
    content = text.encode('utf-8')
    if destination.exists() and destination.read_bytes() != content:
        raise MinerUError('Existing Markdown differs; refusing to overwrite')
    # Validate all conflicts before copying anything into an existing vault.
    for source, target in images.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open('xb') as handle, source.open('rb') as original:
                shutil.copyfileobj(original, handle)
    if not destination.exists():
        with destination.open('xb') as handle:
            handle.write(content)
    return destination
