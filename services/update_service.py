from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QThread, Signal


UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/Anhquocqh25/"
    "Cloakbrowser-Login-Pro/main/release/latest.json"
)
UPDATE_USER_AGENT = "CloakBrowser-Login-Pro-Updater"


@dataclass(frozen=True)
class AppUpdateInfo:
    version: str
    notes: str
    portable_url: str
    portable_sha256: str
    installer_url: str
    installer_sha256: str

    @classmethod
    def from_payload(cls, payload: dict) -> "AppUpdateInfo":
        version = str(payload.get("version") or "").strip().lstrip("v")
        if not re.fullmatch(r"\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?", version):
            raise ValueError("The update manifest contains an invalid version.")
        return cls(
            version=version,
            notes=str(payload.get("notes") or "").strip(),
            portable_url=_valid_download_url(payload.get("portable_url")),
            portable_sha256=_valid_sha256(payload.get("portable_sha256")),
            installer_url=_valid_download_url(payload.get("installer_url")),
            installer_sha256=_valid_sha256(payload.get("installer_sha256")),
        )


def _valid_download_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("The update manifest contains an invalid download URL.")
    return url


def _valid_sha256(value: object) -> str:
    digest = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("The update manifest contains an invalid SHA-256 checksum.")
    return digest


def _version_key(version: str) -> tuple[int, ...]:
    numeric = version.split("-", 1)[0].split("+", 1)[0]
    parts = [int(item) for item in numeric.split(".") if item.isdigit()]
    return tuple((parts + [0, 0, 0, 0])[:4])


def is_newer_version(candidate: str, current: str) -> bool:
    return _version_key(candidate) > _version_key(current)


def fetch_update_info(timeout: float = 15.0) -> AppUpdateInfo:
    separator = "&" if "?" in UPDATE_MANIFEST_URL else "?"
    request = urllib.request.Request(
        f"{UPDATE_MANIFEST_URL}{separator}t={int(time.time())}",
        headers={"User-Agent": UPDATE_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"GitHub returned HTTP {error.code} while checking updates.") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"Could not connect to GitHub: {error}") from error
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("GitHub returned invalid update information.") from error
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned invalid update information.")
    return AppUpdateInfo.from_payload(payload)


def installation_mode(application_dir: Path | None = None) -> str:
    if not getattr(sys, "frozen", False) and application_dir is None:
        return "development"
    directory = Path(application_dir or Path(sys.executable).resolve().parent)
    return "installed" if any(directory.glob("unins*.exe")) else "portable"


def update_asset(info: AppUpdateInfo, mode: str) -> tuple[str, str]:
    if mode == "portable":
        return info.portable_url, info.portable_sha256
    return info.installer_url, info.installer_sha256


def download_update(
    url: str,
    expected_sha256: str,
    progress_callback=None,
    timeout: float = 30.0,
) -> Path:
    target_dir = Path(tempfile.mkdtemp(prefix="cloakbrowser-login-update-"))
    file_name = Path(urlparse(url).path).name or "CloakBrowser-Update.bin"
    target = target_dir / file_name
    request = urllib.request.Request(url, headers={"User-Agent": UPDATE_USER_AGENT})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, target.open("wb") as stream:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(min(100, int(downloaded * 100 / total)))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as error:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(f"Could not download the update: {error}") from error
    if digest.hexdigest().lower() != expected_sha256.lower():
        target.unlink(missing_ok=True)
        raise RuntimeError("The downloaded update failed SHA-256 verification.")
    if progress_callback:
        progress_callback(100)
    return target


def _extract_portable_archive(archive_path: Path) -> Path:
    destination = archive_path.parent / "extracted"
    try:
        with zipfile.ZipFile(archive_path) as archive:
            root = destination.resolve()
            for member in archive.infolist():
                candidate = (destination / member.filename).resolve()
                if root != candidate and root not in candidate.parents:
                    raise RuntimeError("The portable update contains an unsafe path.")
            archive.extractall(destination)
    except (OSError, zipfile.BadZipFile) as error:
        raise RuntimeError("The portable update ZIP is invalid.") from error

    children = [item for item in destination.iterdir() if item.name != "__MACOSX"]
    source = children[0] if len(children) == 1 and children[0].is_dir() else destination
    if not (source / "CloakBrowser Login.exe").is_file():
        raise RuntimeError("The portable update does not contain CloakBrowser Login.exe.")
    return source


def launch_downloaded_update(
    update_path: Path,
    mode: str,
    application_dir: Path | None = None,
    process_id: int | None = None,
) -> None:
    update_path = Path(update_path).resolve()
    if mode != "portable":
        subprocess.Popen(
            [str(update_path), "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
            close_fds=True,
        )
        return

    source = _extract_portable_archive(update_path)
    target = Path(application_dir or Path(sys.executable).resolve().parent).resolve()
    executable = target / "CloakBrowser Login.exe"
    script = update_path.parent / "apply-portable-update.ps1"
    log_path = update_path.parent / "portable-update.log"
    script.write_text(
        "param([int]$ProcessId,[string]$Source,[string]$Target,[string]$Executable,[string]$LogPath)\n"
        "$ErrorActionPreference = 'Stop'\n"
        "try {\n"
        "  Wait-Process -Id $ProcessId -ErrorAction SilentlyContinue\n"
        "  Start-Sleep -Milliseconds 700\n"
        "  Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {\n"
        "    Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force\n"
        "  }\n"
        "  Start-Process -FilePath $Executable -WorkingDirectory $Target\n"
        "} catch {\n"
        "  $_ | Out-String | Set-Content -LiteralPath $LogPath -Encoding UTF8\n"
        "}\n",
        encoding="utf-8-sig",
    )
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-File", str(script),
            "-ProcessId", str(process_id or os.getpid()),
            "-Source", str(source), "-Target", str(target),
            "-Executable", str(executable), "-LogPath", str(log_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )


class UpdateCheckThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.completed.emit(fetch_update_info())
        except Exception as error:
            self.failed.emit(str(error))


class UpdateDownloadThread(QThread):
    progress = Signal(int)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, sha256: str, parent=None) -> None:
        super().__init__(parent)
        self.url = url
        self.sha256 = sha256

    def run(self) -> None:
        try:
            path = download_update(self.url, self.sha256, self.progress.emit)
            self.completed.emit(str(path))
        except Exception as error:
            self.failed.emit(str(error))
