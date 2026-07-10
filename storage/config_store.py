from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from config import APP_BASE_DIR
from utils.paths import ensure_app_directories


class ConfigStore:
    """Small atomic JSON store for UI preferences only."""

    def __init__(self, path: Path | None = None) -> None:
        ensure_app_directories()
        self.path = path or (APP_BASE_DIR / "ui_config.json")
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        with self._lock:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                return {}

    def _write(self, data: dict[str, Any]) -> None:
        with self._lock:
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)

    def get(self, key: str, default: Any = None) -> Any:
        data: Any = self._read()
        for segment in key.split("."):
            if not isinstance(data, dict) or segment not in data:
                return default
            data = data[segment]
        return data

    def set(self, key: str, value: Any) -> None:
        data = self._read()
        target = data
        segments = key.split(".")
        for segment in segments[:-1]:
            target = target.setdefault(segment, {})
        target[segments[-1]] = value
        self._write(data)

    def visible_columns(self, defaults: list[str]) -> list[str]:
        value = self.get("profiles.visible_columns", defaults)
        return [str(item) for item in value] if isinstance(value, list) else list(defaults)

    def set_visible_columns(self, columns: list[str]) -> None:
        self.set("profiles.visible_columns", columns)

    def column_widths(self) -> dict[str, int]:
        value = self.get("profiles.column_widths", {})
        if not isinstance(value, dict):
            return {}
        return {str(key): int(width) for key, width in value.items() if isinstance(width, (int, float))}

    def set_column_widths(self, widths: dict[str, int]) -> None:
        self.set("profiles.column_widths", widths)

    def default_startup_url(self) -> str:
        value = self.get("browser.default_startup_url", "")
        return str(value).strip() if isinstance(value, str) else ""

    def set_default_startup_url(self, url: str) -> None:
        self.set("browser.default_startup_url", url.strip())

    def language(self) -> str:
        value = self.get("interface.language", "en")
        return value if value in {"en", "vi"} else "en"

    def set_language(self, language: str) -> None:
        self.set("interface.language", language if language in {"en", "vi"} else "en")

    def profile_sort(self) -> str:
        value = self.get("profiles.sort", "created_desc")
        allowed = {
            "created_desc", "created_asc", "name_asc", "name_desc",
            "status", "proxy",
        }
        return value if value in allowed else "created_desc"

    def set_profile_sort(self, sort_key: str) -> None:
        self.set("profiles.sort", sort_key)

    def profile_density(self) -> str:
        value = str(self.get("profiles.density", "comfortable") or "comfortable")
        return value if value in {"compact", "comfortable", "wide"} else "comfortable"

    def set_profile_density(self, density: str) -> None:
        self.set("profiles.density", density if density in {"compact", "comfortable", "wide"} else "comfortable")

    def trash_retention_days(self) -> int:
        value = int(self.get("trash.retention_days", 15) or 15)
        return value if value in {7, 15, 30} else 15

    def set_trash_retention_days(self, days: int) -> None:
        self.set("trash.retention_days", days if days in {7, 15, 30} else 15)

    def automatic_backup_enabled(self) -> bool:
        return bool(self.get("backup.automatic", False))

    def set_automatic_backup_enabled(self, enabled: bool) -> None:
        self.set("backup.automatic", bool(enabled))

    def backup_interval_days(self) -> int:
        value = int(self.get("backup.interval_days", 1) or 1)
        return value if value in {1, 3, 7} else 1

    def set_backup_interval_days(self, days: int) -> None:
        self.set("backup.interval_days", days if days in {1, 3, 7} else 1)

    def last_backup_at(self) -> str:
        return str(self.get("backup.last_at", "") or "")

    def set_last_backup_at(self, timestamp: str) -> None:
        self.set("backup.last_at", timestamp)

    def cloak_browser_version(self) -> str:
        return str(self.get("browser.cloak_version", "") or "").strip()

    def set_cloak_browser_version(self, version: str) -> None:
        self.set("browser.cloak_version", str(version or "").strip())

    def onboarding_completed(self) -> bool:
        return bool(self.get("experience.onboarding_completed", False))

    def set_onboarding_completed(self, completed: bool = True) -> None:
        self.set("experience.onboarding_completed", bool(completed))

    def last_page(self) -> int:
        try:
            return max(0, int(self.get("experience.last_page", 12) or 12))
        except (TypeError, ValueError):
            return 12

    def set_last_page(self, page: int) -> None:
        self.set("experience.last_page", max(0, int(page)))

    def sidebar_collapsed(self) -> bool:
        return bool(self.get("experience.sidebar_collapsed", False))

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        self.set("experience.sidebar_collapsed", bool(collapsed))

    def profile_presets(self) -> list[dict[str, Any]]:
        value = self.get("experience.profile_presets", [])
        return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def set_profile_presets(self, presets: list[dict[str, Any]]) -> None:
        self.set("experience.profile_presets", presets)

    def saved_views(self) -> list[dict[str, Any]]:
        value = self.get("experience.saved_views", [])
        return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def set_saved_views(self, views: list[dict[str, Any]]) -> None:
        self.set("experience.saved_views", views)

    def proxy_pool_enabled(self) -> bool:
        return bool(self.get("proxy_pool.enabled", True))

    def set_proxy_pool_enabled(self, enabled: bool) -> None:
        self.set("proxy_pool.enabled", bool(enabled))

    def proxy_pool_interval_minutes(self) -> int:
        try:
            value = int(self.get("proxy_pool.interval_minutes", 30) or 30)
        except (TypeError, ValueError):
            value = 30
        return value if value in {5, 15, 30, 60, 180} else 30

    def set_proxy_pool_interval_minutes(self, minutes: int) -> None:
        self.set("proxy_pool.interval_minutes", minutes if minutes in {5, 15, 30, 60, 180} else 30)
