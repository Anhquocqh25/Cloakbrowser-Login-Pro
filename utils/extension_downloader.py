from __future__ import annotations

import io
import json
import re
import shutil
import struct
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode, urlparse

import httpx

from config import EXTENSION_STORAGE_DIR


MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_EXTRACTED_BYTES = 150 * 1024 * 1024
MAX_ARCHIVE_FILES = 5000
CHROME_WEB_STORE_UPDATE_URL = "https://clients2.google.com/service/update2/crx"
EXTENSION_ID_RE = re.compile(r"(?<![a-p])([a-p]{32})(?![a-p])")


def _chrome_web_store_download_url(source_url: str) -> str | None:
    host = (urlparse(source_url).hostname or "").lower()
    if host not in {"chromewebstore.google.com", "chrome.google.com"}:
        return None
    match = EXTENSION_ID_RE.search(source_url.lower())
    if not match:
        raise ValueError("Chrome Web Store URL does not contain a valid extension ID.")
    query = urlencode({
        "response": "redirect",
        "prodversion": "146.0.0.0",
        "acceptformat": "crx2,crx3",
        "x": f"id={match.group(1)}&installsource=ondemand&uc",
    })
    return f"{CHROME_WEB_STORE_UPDATE_URL}?{query}"


def _github_archive_url(source_url: str) -> str | None:
    parsed = urlparse(source_url)
    if (parsed.hostname or "").lower() != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("GitHub URL must point to a repository or ZIP archive.")
    owner, repository = parts[0], parts[1].removesuffix(".git")
    if parsed.path.lower().endswith((".zip", ".crx")):
        return source_url
    if len(parts) >= 4 and parts[2] in {"tree", "commit"}:
        ref = parts[3]
        return f"https://github.com/{owner}/{repository}/archive/{ref}.zip"
    return f"https://github.com/{owner}/{repository}/archive/HEAD.zip"


def normalize_download_url(source_url: str) -> str:
    clean_url = source_url.strip()
    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Extension URL must start with http:// or https://.")
    return _chrome_web_store_download_url(clean_url) or _github_archive_url(clean_url) or clean_url


def download_archive(source_url: str) -> bytes:
    download_url = normalize_download_url(source_url)
    headers = {"User-Agent": "Mozilla/5.0 CloakBrowser-Manager/0.2"}
    data = bytearray()
    try:
        with httpx.Client(follow_redirects=True, timeout=90.0, headers=headers) as client:
            with client.stream("GET", download_url) as response:
                response.raise_for_status()
                content_length = int(response.headers.get("content-length") or 0)
                if content_length > MAX_DOWNLOAD_BYTES:
                    raise ValueError("Extension package is larger than 50 MB.")
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_DOWNLOAD_BYTES:
                        raise ValueError("Extension package is larger than 50 MB.")
    except httpx.HTTPError as error:
        raise ValueError(f"Could not download extension: {error}") from error
    if not data:
        raise ValueError("The extension download returned an empty file.")
    return bytes(data)


def crx_to_zip(package: bytes) -> bytes:
    if package.startswith(b"PK\x03\x04"):
        return package
    if not package.startswith(b"Cr24") or len(package) < 12:
        raise ValueError("URL did not return a valid CRX or ZIP extension package.")
    version = struct.unpack_from("<I", package, 4)[0]
    if version == 2:
        if len(package) < 16:
            raise ValueError("Invalid CRX2 header.")
        public_key_length, signature_length = struct.unpack_from("<II", package, 8)
        offset = 16 + public_key_length + signature_length
    elif version == 3:
        header_length = struct.unpack_from("<I", package, 8)[0]
        offset = 12 + header_length
    else:
        raise ValueError(f"Unsupported CRX version: {version}.")
    if offset >= len(package) or not package[offset:].startswith(b"PK\x03\x04"):
        raise ValueError("CRX package does not contain a valid ZIP payload.")
    return package[offset:]


def _safe_extract(zip_bytes: bytes, destination: Path) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as error:
        raise ValueError("Extension package contains an invalid ZIP archive.") from error
    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_FILES:
            raise ValueError("Extension archive contains too many files.")
        if sum(entry.file_size for entry in entries) > MAX_EXTRACTED_BYTES:
            raise ValueError("Extracted extension would be larger than 150 MB.")
        for entry in entries:
            relative = PurePosixPath(entry.filename.replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Extension archive contains an unsafe file path.")
            if entry.is_dir():
                continue
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _find_extension_root(extracted: Path) -> Path:
    manifests = [
        path for path in extracted.rglob("manifest.json")
        if "__MACOSX" not in path.parts and "node_modules" not in path.parts
    ]
    if not manifests:
        raise ValueError("Downloaded package does not contain manifest.json.")
    manifest = min(manifests, key=lambda path: (len(path.relative_to(extracted).parts), len(str(path))))
    if len(manifest.relative_to(extracted).parts) > 6:
        raise ValueError("manifest.json is nested too deeply in the downloaded package.")
    try:
        content = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except Exception as error:
        raise ValueError(f"Could not read downloaded manifest.json: {error}") from error
    if not isinstance(content, dict) or not content.get("name") or not content.get("version"):
        raise ValueError("manifest.json is missing the extension name or version.")
    if int(content.get("manifest_version") or 0) not in {2, 3}:
        raise ValueError("Only Manifest V2 and V3 extensions are supported.")
    return manifest.parent


def install_extension_package(package: bytes) -> Path:
    EXTENSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cloak-extension-") as temp_dir:
        extracted = Path(temp_dir)
        _safe_extract(crx_to_zip(package), extracted)
        extension_root = _find_extension_root(extracted)
        destination = EXTENSION_STORAGE_DIR / str(uuid.uuid4())
        try:
            shutil.copytree(extension_root, destination)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
    return destination


def download_and_install_extension(source_url: str) -> Path:
    return install_extension_package(download_archive(source_url))
