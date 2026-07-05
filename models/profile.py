from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from config import DEFAULT_LOCALE, DEFAULT_SCREEN_HEIGHT, DEFAULT_SCREEN_WIDTH, DEFAULT_TIMEZONE


@dataclass(slots=True)
class Profile:
    id: str
    name: str
    proxy: str | None = None
    timezone: str = DEFAULT_TIMEZONE
    locale: str = DEFAULT_LOCALE
    screen_width: int = DEFAULT_SCREEN_WIDTH
    screen_height: int = DEFAULT_SCREEN_HEIGHT
    fingerprint_seed: int | None = None
    auto_geoip: bool = True
    platform: str = "windows"
    browser_engine: str = "cloak"
    notes: str = ""
    user_agent: str = ""
    startup_url: str = ""
    extension_ids: list[str] | None = None
    bookmark_ids: list[str] | None = None
    status: str = "stopped"
    deleted_at: str = ""
    group_name: str = ""
    tags: str = ""
    pinned: bool = False
    last_used_at: str = ""
    health_status: str = "unknown"
    health_checked_at: str = ""
    seed_locked: bool = False
    created_at: str = ""
    updated_at: str = ""
    # Effective app-wide pin. It is injected before launch and is intentionally
    # not persisted per profile.
    cloak_version: str = ""

    @property
    def screen_size_label(self) -> str:
        return f"{self.screen_width}x{self.screen_height}"

    @classmethod
    def now_timestamp(cls) -> str:
        return datetime.utcnow().isoformat(timespec="seconds")

    @classmethod
    def from_row(cls, row: Any) -> "Profile":
        return cls(
            id=row["id"],
            name=row["name"],
            proxy=row["proxy"],
            timezone=row["timezone"],
            locale=row["locale"],
            screen_width=row["screen_width"],
            screen_height=row["screen_height"],
            fingerprint_seed=row["fingerprint_seed"],
            auto_geoip=bool(row["auto_geoip"]),
            platform=row["platform"],
            browser_engine=row["browser_engine"],
            notes=row["notes"],
            user_agent=row["user_agent"],
            startup_url=row["startup_url"],
            extension_ids=_json_ids(row["extension_ids"]),
            bookmark_ids=_json_ids(row["bookmark_ids"]),
            status=row["status"],
            deleted_at=row["deleted_at"],
            group_name=row["group_name"],
            tags=row["tags"],
            pinned=bool(row["pinned"]),
            last_used_at=row["last_used_at"],
            health_status=row["health_status"],
            health_checked_at=row["health_checked_at"],
            seed_locked=bool(row["seed_locked"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_db_tuple(self) -> tuple[Any, ...]:
        return (
            self.id,
            self.name,
            self.proxy,
            self.timezone,
            self.locale,
            self.screen_width,
            self.screen_height,
            self.fingerprint_seed,
            int(self.auto_geoip),
            self.platform,
            self.browser_engine,
            self.notes,
            self.user_agent,
            self.startup_url,
            _dump_ids(self.extension_ids),
            _dump_ids(self.bookmark_ids),
            self.status,
            self.deleted_at,
            self.group_name,
            self.tags,
            int(self.pinned),
            self.last_used_at,
            self.health_status,
            self.health_checked_at,
            int(self.seed_locked),
            self.created_at,
            self.updated_at,
        )


def _json_ids(value: str | None) -> list[str] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(value)
        return [str(item) for item in decoded] if isinstance(decoded, list) else None
    except (TypeError, ValueError):
        return None


def _dump_ids(value: list[str] | None) -> str | None:
    return json.dumps(list(dict.fromkeys(value))) if value is not None else None
