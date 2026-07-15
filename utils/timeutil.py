from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def utc_iso(timespec: str = "seconds") -> str:
    """ISO-8601 UTC timestamp (always includes offset)."""
    return utc_now().isoformat(timespec=timespec)


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse ISO timestamps from older naive or newer offset forms into aware UTC."""
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_older_than(value: str | None, delta: timedelta) -> bool:
    parsed = parse_iso_datetime(value)
    if parsed is None:
        return False
    return parsed < utc_now() - delta
