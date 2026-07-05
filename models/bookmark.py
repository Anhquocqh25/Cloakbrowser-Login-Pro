from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BookmarkRecord:
    id: str
    title: str
    url: str
    folder: str = "Fingerprint Tests"
    created_at: str = ""

    @classmethod
    def from_row(cls, row: Any) -> "BookmarkRecord":
        return cls(
            id=row["id"], title=row["title"], url=row["url"],
            folder=row["folder"], created_at=row["created_at"],
        )
