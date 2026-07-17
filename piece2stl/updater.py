from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GITHUB_OWNER = "suceunq"
GITHUB_REPO = "Piece2STL"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    installer_url: str
    checksum_url: str


def _version_tuple(value: str) -> tuple[int, ...]:
    clean = value.strip().lstrip("vV").split("-", 1)[0]
    try:
        return tuple(int(part) for part in clean.split("."))
    except ValueError:
        return (0,)


def check_for_update(current_version: str) -> UpdateInfo | None:
    request = Request(LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "Piece2STL-Updater"})
    try:
        with urlopen(request, timeout=12) as response:
            release = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(f"GitHub a répondu avec l’erreur {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Serveur de mise à jour injoignable : {exc.reason}") from exc
    version = str(release.get("tag_name") or "").lstrip("vV")
    if _version_tuple(version) <= _version_tuple(current_version):
        return None
    assets = release.get("assets") or []
    installer = next((a for a in assets if a.get("name", "").lower().endswith("setup.exe")), None)
    checksum = next((a for a in assets if a.get("name", "").lower().endswith("setup.exe.sha256")), None)
    if not installer or not checksum:
        raise RuntimeError("La Release ne contient pas l’installateur et sa somme SHA-256.")
    return UpdateInfo(version, str(release.get("body") or ""), installer["browser_download_url"], checksum["browser_download_url"])


def download_update(info: UpdateInfo, progress=None) -> Path:
    destination = Path(tempfile.gettempdir()) / f"Piece2STL-Setup-{info.version}.exe"
    request = Request(info.installer_url, headers={"User-Agent": "Piece2STL-Updater"})
    with urlopen(request, timeout=120) as response, destination.open("wb") as output:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            received += len(chunk)
            if progress and total:
                progress(min(100, round(received * 100 / total)))
    with urlopen(Request(info.checksum_url, headers={"User-Agent": "Piece2STL-Updater"}), timeout=20) as response:
        expected = response.read().decode("ascii", errors="ignore").strip().split()[0].lower()
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != expected:
        destination.unlink(missing_ok=True)
        raise RuntimeError("La signature SHA-256 de la mise à jour est incorrecte. Installation annulée.")
    return destination
