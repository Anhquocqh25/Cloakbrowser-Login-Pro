from __future__ import annotations

import json
from pathlib import Path

from models.bookmark import BookmarkRecord


def write_bookmark_config(
    extension_dir: Path,
    bookmarks: list[BookmarkRecord],
    profile_name: str = "",
) -> None:
    extension_dir.mkdir(parents=True, exist_ok=True)
    folders = sorted({item.folder or "Bookmarks" for item in bookmarks} | {"Fingerprint Tests"})
    payload = {
        "profileName": " ".join(profile_name.split()).strip(),
        "folders": folders,
        "items": [
            {"title": item.title, "url": item.url, "folder": item.folder or "Bookmarks"}
            for item in bookmarks
        ],
    }
    target = extension_dir / "bookmarks.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
