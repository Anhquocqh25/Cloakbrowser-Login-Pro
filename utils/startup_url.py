from __future__ import annotations

from urllib.parse import urlsplit


def normalize_startup_url(value: str | None) -> str:
    """Return a safe HTTP(S) startup URL, adding https:// when omitted."""
    clean = (value or "").strip()
    if not clean:
        return ""
    if "://" not in clean:
        clean = f"https://{clean}"
    parsed = urlsplit(clean)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Startup website must be a valid http:// or https:// address.")
    return clean
