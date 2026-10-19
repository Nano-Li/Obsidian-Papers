"""MinerU v4 client and safe archive extraction, copied from AutoPaper.

API sequence follows Nano-Li/minerU-kit (db9e99b); implemented here using the
existing curl-cffi dependency. No upstream checkout is required at runtime.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tomllib
import uuid
import zipfile

from curl_cffi import requests


API = "https://mineru.net/api/v4"


class MinerUError(RuntimeError):
    def __init__(self, message: str, *, stop: bool = False):
        super().__init__(message)
        self.stop = stop


@dataclass(frozen=True)
class Settings:
    token: str = field(repr=False)
    model: str = "pipeline"
    language: str = "en"
    ocr: bool = False
    network_mode: str = "direct"
    proxy_url: str = ""
    poll_seconds: int = 10
    timeout_seconds: int = 1800

    def options(self) -> dict:
        return dict(model_version=self.model, language=self.language,
                    enable_formula=True, enable_table=True)


def load_settings(path: str | Path) -> Settings:
    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)["mineru"]
    settings = Settings(**data)
    if settings.model not in {"pipeline", "vlm"}:
        raise ValueError("MinerU model must be pipeline or vlm")
    if settings.network_mode not in {"direct", "proxy"}:
        raise ValueError("MinerU network_mode must be direct or proxy")
    if settings.network_mode == "proxy" and not settings.proxy_url:
        raise ValueError("MinerU proxy mode requires proxy_url")
    if settings.poll_seconds < 3 or settings.timeout_seconds < 1:
        raise ValueError("Invalid MinerU polling interval or timeout")
    return settings


@contextmanager
def conversion_lock(pdf: Path):
    """OS lock is released on process exit, including interrupted runs."""
    path = Path(str(pdf) + ".mineru.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if __import__("os").name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise MinerUError("Another Markdown conversion is using this PDF") from None
        try:
            yield
        finally:
            handle.seek(0)
            if __import__("os").name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def staging_directory(parent: Path):
    # Ordinary inherited permissions: Windows tempfile's private ACL would follow
    # a renamed output directory and prevent other workspace readers opening it.
    root = parent.resolve()
    staging = root / (".mineru-" + uuid.uuid4().hex)
    staging.mkdir()
    try:
        yield staging
    finally:
        if staging.resolve().parent == root and staging.name.startswith(".mineru-"):
            shutil.rmtree(staging)


class Client:
    def __init__(self, settings: Settings):
        self.settings = settings
        # Explicitly ignore environment/OS proxies unless configured here.
        proxy = settings.proxy_url if settings.network_mode == "proxy" else ""
        self.session = requests.Session(trust_env=False, proxies={"all": proxy})

    def close(self):
        self.session.close()

    def request(self, method: str, url: str, *, authenticated=False, **kwargs):
        if not url.startswith("https://"):
            raise MinerUError("MinerU returned a non-HTTPS URL")
        headers = {"Authorization": f"Bearer {self.settings.token}"} if authenticated else {}
        if method == "PUT":
            # curl-cffi otherwise inserts application/octet-stream for byte bodies.
            headers["Content-Type"] = None
        try:
            response = self.session.request(
                method, url, headers=headers, timeout=120,
                allow_redirects=not authenticated, **kwargs,
            )
        except requests.RequestsError:
            # Exception strings may contain signed URLs. Never log them.
            raise MinerUError("Network request failed; retry to resume the saved task") from None
        if not 200 <= response.status_code < 300:
            code = response.status_code
            response.close()
            raise MinerUError(f"HTTP {code}" + ("; check token/quota" if authenticated else ""),
                              stop=authenticated and code in {401, 403, 429})
        return response

    def api(self, method: str, path: str, **kwargs) -> dict:
        response = self.request(method, API + path, authenticated=True, **kwargs)
        try:
            data = response.json()
        except ValueError:
            raise MinerUError("MinerU returned invalid JSON") from None
        finally:
            response.close()
        if data.get("code") != 0:
            # Codes are enough to diagnose without echoing server-provided secrets.
            raise MinerUError(f"MinerU API error code: {data.get('code')}", stop=True)
        return data.get("data") or {}

    def submit(self, code: str) -> tuple[str, str]:
        body = self.settings.options()
        body["files"] = [{"name": code + ".pdf", "data_id": code,
                          "is_ocr": self.settings.ocr}]
        data = self.api("POST", "/file-urls/batch", json=body)
        if not data.get("batch_id") or len(data.get("file_urls", [])) != 1:
            raise MinerUError("MinerU response lacks a batch ID or upload URL", stop=True)
        return data["batch_id"], data["file_urls"][0]

    def upload(self, url: str, pdf: Path):
        # Signed upload: no Authorization or Content-Type headers (upstream rule).
        response = self.request("PUT", url, data=pdf.read_bytes())
        response.close()

    def result(self, batch_id: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", batch_id):
            raise MinerUError("Invalid saved batch ID")
        data = self.api("GET", "/extract-results/batch/" + batch_id)
        results = data.get("extract_result") or []
        if len(results) > 1:
            raise MinerUError("Unexpected multiple results for a single-paper task")
        return results[0] if results else {}

    def download(self, url: str, path: Path):
        response = self.request("GET", url, stream=True)
        try:
            with path.open("wb") as handle:
                total = 0
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    total += len(chunk)
                    if total > 512 * 1024 * 1024:
                        raise MinerUError("Result archive exceeds 512 MB")
                    handle.write(chunk)
        except requests.RequestsError:
            raise MinerUError("Result download interrupted; retry to resume") from None
        finally:
            response.close()


def extract_result(archive: Path, destination: Path) -> Path:
    """Validate before extracting; never accept archive paths outside output."""
    with zipfile.ZipFile(archive) as bundle:
        members = []
        size = 0
        for info in bundle.infolist():
            name = PurePosixPath(info.filename.replace("\\", "/"))
            if (name.is_absolute() or ".." in name.parts or ":" in str(name)
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise MinerUError("Unsafe path in MinerU result archive")
            if info.is_dir() or "__MACOSX" in name.parts or name.suffix.lower() == ".pdf":
                continue
            size += info.file_size
            if size > 1024 * 1024 * 1024 or len(members) >= 20000:
                raise MinerUError("MinerU result archive is too large")
            members.append((info, name))
        markdowns = [(info, name) for info, name in members if name.suffix.lower() == ".md"]
        preferred = [item for item in markdowns if item[1].name == "full.md"]
        choices = preferred or markdowns
        if len(choices) != 1 or not bundle.read(choices[0][0]).decode("utf-8-sig").strip():
            raise MinerUError("Result must contain one identifiable, nonempty Markdown document")
        # Validate all names before touching the output directory.
        for info, name in members:
            target = destination.joinpath(*name.parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise MinerUError("Unsafe output path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    return destination.joinpath(*choices[0][1].parts)
