from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ExtensionRecord:
    id: str
    name: str
    path: str
    enabled: bool = True
    created_at: str = ""

    @classmethod
    def from_row(cls, row: Any) -> "ExtensionRecord":
        return cls(
            id=row["id"], name=row["name"], path=row["path"],
            enabled=bool(row["enabled"]), created_at=row["created_at"],
        )
