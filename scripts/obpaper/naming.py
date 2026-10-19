"""Title helpers copied from Nano-Li/minerU-kit db9e99b (mineru_client.py)."""
import json
from pathlib import Path
import re


def _extract_title_from_layout(layout_path: Path) -> str | None:
    """
    Read layout.json and return the text of the first type='title' block on page 0.
    Returns None if the file is missing, unreadable, or contains no title block.
    """
    try:
        layout = json.loads(layout_path.read_bytes().decode("utf-8"))
        page0  = (layout.get("pdf_info") or [{}])[0]
        for block in page0.get("para_blocks", []):
            if block.get("type") == "title":
                text = " ".join(
                    span.get("content", "")
                    for line in block.get("lines", [])
                    for span in line.get("spans", [])
                ).strip()
                if text:
                    return text
    except Exception:
        pass
    return None


def _clean_for_path(title: str) -> str:
    """
    Sanitise a string for use as a folder / file name:
      - strip Windows/POSIX reserved chars:  \\ / : * ? " < > |
      - replace whitespace runs with a single _
      - collapse consecutive _ into one
      - strip leading/trailing dots and _
      - truncate to 120 characters
    """
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title)
    cleaned = re.sub(r"\s+",                   "_", cleaned)
    cleaned = re.sub(r"_+",                    "_", cleaned)
    cleaned = cleaned.strip("._")
    return cleaned[:120] or "untitled"


def title_filename(title: str) -> str:
    # Obsidian adds link-reserved characters; otherwise use upstream verbatim.
    value = _clean_for_path(re.sub(r'[\[\]#^]', '', title))
    if value == 'untitled' and not title.strip():
        raise ValueError('Paper title is empty')
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', value, re.I):
        value = '_' + value
    while len(value.encode('utf-8')) > 180:
        value = value[:-1]
    return value.rstrip(' ._') or 'untitled'
