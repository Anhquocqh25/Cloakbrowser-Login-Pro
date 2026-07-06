from __future__ import annotations

import re
from urllib.parse import urlsplit


def normalize_startup_url(value: str | None) -> str:
    """Return one or more safe HTTP(S) startup URLs.

    Multiple URLs may be separated with a comma, semicolon, pipe or a newline.
    The normalized value is stored comma-separated so it remains readable in
    simple one-line fields.
    """
    return ", ".join(normalize_startup_urls(value))


def normalize_startup_urls(value: str | None) -> list[str]:
    """Return normalized startup URLs, adding https:// when omitted."""
    clean = (value or "").strip()
    if not clean:
        return []
    normalized: list[str] = []
    for raw_item in re.split(r"[\n,;|]+", clean):
        item = raw_item.strip()
        if not item:
            continue
        if "://" not in item:
            item = f"https://{item}"
        parsed = urlsplit(item)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Startup website must be a valid http:// or https:// address.")
        if item not in normalized:
            normalized.append(item)
    return normalized


def startup_url_args(value: str | None) -> list[str]:
    urls = normalize_startup_urls(value)
    return urls or ["about:blank"]
