from __future__ import annotations

import base64
import ctypes
import os
import sys
from ctypes import wintypes


# Versioned marker so plaintext legacy values remain readable during migration.
SECRET_PREFIX = "cbenc1:"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def is_encrypted(value: str | None) -> bool:
    return bool(value) and str(value).startswith(SECRET_PREFIX)


def encrypt_secret(plaintext: str | None) -> str | None:
    """Protect a secret for local storage. Returns None when input is empty."""
    if plaintext is None:
        return None
    text = str(plaintext)
    if not text:
        return text
    if is_encrypted(text):
        return text
    if os.name != "nt":
        # App is Windows-first; keep a clear marker if ever run elsewhere.
        return text
    protected = _dpapi_protect(text.encode("utf-8"))
    return SECRET_PREFIX + base64.urlsafe_b64encode(protected).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    """Reveal a secret. Legacy plaintext values are returned unchanged."""
    if value is None:
        return None
    text = str(value)
    if not text or not is_encrypted(text):
        return text
    if os.name != "nt":
        raise OSError("Encrypted secrets can only be decrypted on Windows.")
    payload = text[len(SECRET_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
    except (ValueError, UnicodeError) as error:
        raise OSError("Stored secret encoding is invalid.") from error
    return _dpapi_unprotect(raw).decode("utf-8")


def encrypt_proxy_field(value: str | None) -> str | None:
    """Encrypt proxy URL for SQLite / sidecar storage."""
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    return encrypt_secret(clean)


def decrypt_proxy_field(value: str | None) -> str | None:
    """Decrypt proxy URL after loading from storage."""
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    return decrypt_secret(clean)


def _dpapi_protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = DATA_BLOB(len(data), ctypes.create_string_buffer(data))
    blob_out = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        "CloakBrowser Login",
        None,
        None,
        None,
        0x1,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(blob_out),
    ):
        raise OSError(f"CryptProtectData failed ({ctypes.GetLastError()}).")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = DATA_BLOB(len(data), ctypes.create_string_buffer(data))
    blob_out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0x1,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(blob_out),
    ):
        raise OSError(f"CryptUnprotectData failed ({ctypes.GetLastError()}).")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def secrets_supported() -> bool:
    return sys.platform == "win32"
