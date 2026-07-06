from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from utils.ip_location import country_code_from_flag_text, strip_flag_prefix


@dataclass(slots=True)
class ProxyRecord:
    id: str
    name: str
    url: str
    location: str = ""
    notes: str = ""
    created_at: str = ""
    status: str = "unknown"
    latency_ms: int = 0
    exit_ip: str = ""
    last_checked_at: str = ""
    check_error: str = ""
    country_code: str = ""
    timezone: str = ""
    enabled: bool = True
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    quality_score: int = 0
    cooldown_until: str = ""

    @property
    def proxy_type(self) -> str:
        return self.url.split(":", 1)[0].upper() if ":" in self.url else "HTTP"

    @classmethod
    def from_row(cls, row: Any) -> "ProxyRecord":
        stored_location = row["location"] or ""
        stored_code = row["country_code"] or country_code_from_flag_text(stored_location)
        return cls(
            id=row["id"], name=row["name"], url=row["url"],
            location=strip_flag_prefix(stored_location), notes=row["notes"], created_at=row["created_at"],
            status=row["status"], latency_ms=int(row["latency_ms"] or 0),
            exit_ip=row["exit_ip"], last_checked_at=row["last_checked_at"],
            check_error=row["check_error"],
            country_code=stored_code, timezone=row["geo_timezone"],
            enabled=bool(row["enabled"]), success_count=int(row["success_count"] or 0),
            failure_count=int(row["failure_count"] or 0),
            consecutive_failures=int(row["consecutive_failures"] or 0),
            quality_score=int(row["quality_score"] or 0),
            cooldown_until=row["cooldown_until"] or "",
        )
