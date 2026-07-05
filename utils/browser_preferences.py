from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DUCKDUCKGO_SEARCH_URL = "https://duckduckgo.com/?q={searchTerms}"
DUCKDUCKGO_SUGGEST_URL = "https://duckduckgo.com/ac/?q={searchTerms}&type=list"


def _merge(target: dict[str, Any], values: dict[str, Any]) -> None:
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


def configure_duckduckgo(user_data_dir: Path) -> bool:
    """Set DuckDuckGo for a Chromium profile without replacing other preferences.

    Chromium keeps browser preferences in ``Default/Preferences``. Existing data
    is merged and the file is replaced atomically so cookies, extensions and
    fingerprint-related profile state remain untouched.
    """
    preferences_path = Path(user_data_dir) / "Default" / "Preferences"
    preferences_path.parent.mkdir(parents=True, exist_ok=True)

    preferences: dict[str, Any] = {}
    if preferences_path.exists():
        try:
            loaded = json.loads(preferences_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            # Never replace an unreadable Chromium profile file. The browser can
            # still launch normally; only the search-engine preference is skipped.
            return False
        if not isinstance(loaded, dict):
            return False
        preferences = loaded

    _merge(
        preferences,
        {
            "default_search_provider": {
                "enabled": True,
                "encodings": "UTF-8",
                "favicon_url": "https://duckduckgo.com/favicon.ico",
                "keyword": "duckduckgo.com",
                "name": "DuckDuckGo",
                "search_url": DUCKDUCKGO_SEARCH_URL,
                "suggest_url": DUCKDUCKGO_SUGGEST_URL,
            },
            "default_search_provider_data": {
                "template_url_data": {
                    "alternate_urls": [],
                    "favicon_url": "https://duckduckgo.com/favicon.ico",
                    "input_encodings": ["UTF-8"],
                    "keyword": "duckduckgo.com",
                    "new_tab_url": "https://duckduckgo.com/",
                    "prepopulate_id": 0,
                    "safe_for_autoreplace": False,
                    "short_name": "DuckDuckGo",
                    "suggestions_url": DUCKDUCKGO_SUGGEST_URL,
                    "url": DUCKDUCKGO_SEARCH_URL,
                }
            },
        },
    )

    temporary = preferences_path.with_name("Preferences.cloak-login.tmp")
    try:
        temporary.write_text(
            json.dumps(preferences, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(preferences_path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True
