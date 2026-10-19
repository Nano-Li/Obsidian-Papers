import re
import unicodedata


def title_filename(title: str) -> str:
    """Keep readable titles; replace filesystem/Obsidian reserved characters."""
    value = unicodedata.normalize("NFC", title)
    value = re.sub(r'[<>:"/\\|?*\[\]#^\x00-\x1f]', '_', value)
    value = re.sub(r'\s+', ' ', value).strip(' .')
    if not value:
        raise ValueError('Paper title is empty')
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', value, re.I):
        value = '_' + value
    # Keep a safe filename byte budget for both Windows and common Linux vaults.
    while len(value.encode('utf-8')) > 180:
        value = value[:-1]
    return value.rstrip(' .')
