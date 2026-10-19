from pathlib import Path

def validate_pdf(path: Path, minimum_bytes: int) -> tuple[bool, str]:
    size = path.stat().st_size
    if size < minimum_bytes:
        return False, f"too_small:{size}"
    with path.open("rb") as handle:
        header = handle.read(8)
    if not header.startswith(b"%PDF-"):
        return False, "missing_pdf_signature"
    return True, "ok"
