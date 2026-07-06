from __future__ import annotations

from datetime import datetime, timedelta

from database.db import get_connection
from models.proxy import ProxyRecord


class ProxyRepository:
    def list_all(self) -> list[ProxyRecord]:
        with get_connection() as connection:
            rows = connection.execute(
                """SELECT id, name, url, location, notes, created_at, status, latency_ms,
                          exit_ip, last_checked_at, check_error, country_code, geo_timezone,
                          enabled, success_count, failure_count, consecutive_failures,
                          quality_score, cooldown_until
                   FROM proxies ORDER BY name COLLATE NOCASE"""
            ).fetchall()
        return [ProxyRecord.from_row(row) for row in rows]

    def get(self, proxy_id: str) -> ProxyRecord | None:
        with get_connection() as connection:
            row = connection.execute(
                """SELECT id, name, url, location, notes, created_at, status, latency_ms,
                          exit_ip, last_checked_at, check_error, country_code, geo_timezone,
                          enabled, success_count, failure_count, consecutive_failures,
                          quality_score, cooldown_until FROM proxies WHERE id = ?""", (proxy_id,)
            ).fetchone()
        return ProxyRecord.from_row(row) if row else None

    def save(self, record: ProxyRecord) -> None:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO proxies (
                       id, name, url, location, notes, created_at, status, latency_ms,
                       exit_ip, last_checked_at, check_error, country_code, geo_timezone,
                       enabled, success_count, failure_count, consecutive_failures,
                       quality_score, cooldown_until
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, url=excluded.url,
                   location=excluded.location, notes=excluded.notes, status=excluded.status,
                   latency_ms=excluded.latency_ms, exit_ip=excluded.exit_ip,
                   last_checked_at=excluded.last_checked_at, check_error=excluded.check_error,
                   country_code=excluded.country_code, geo_timezone=excluded.geo_timezone,
                   enabled=excluded.enabled, success_count=excluded.success_count,
                   failure_count=excluded.failure_count,
                   consecutive_failures=excluded.consecutive_failures,
                   quality_score=excluded.quality_score,
                   cooldown_until=excluded.cooldown_until""",
                (
                    record.id, record.name, record.url, record.location, record.notes,
                    record.created_at, record.status, record.latency_ms, record.exit_ip,
                    record.last_checked_at, record.check_error,
                    record.country_code, record.timezone, int(record.enabled), record.success_count,
                    record.failure_count, record.consecutive_failures, record.quality_score,
                    record.cooldown_until,
                ),
            )
            connection.commit()

    def update_check_result(
        self, proxy_id: str, status: str, latency_ms: int = 0, exit_ip: str = "",
        checked_at: str = "", error: str = "", location: str = "",
        country_code: str = "", timezone: str = "",
    ) -> None:
        current = self.get(proxy_id)
        success, failure, consecutive, enabled, score, cooldown = self._pool_result(current, status, latency_ms, checked_at)
        with get_connection() as connection:
            connection.execute(
                """UPDATE proxies SET status=?, latency_ms=?, exit_ip=?,
                   last_checked_at=?, check_error=?,
                   location=CASE WHEN ? != '' THEN ? ELSE location END,
                   country_code=CASE WHEN ? != '' THEN ? ELSE country_code END,
                   geo_timezone=CASE WHEN ? != '' THEN ? ELSE geo_timezone END,
                   enabled=?, success_count=?, failure_count=?, consecutive_failures=?,
                   quality_score=?, cooldown_until=? WHERE id=?""",
                (status, latency_ms, exit_ip, checked_at, error, location, location,
                 country_code, country_code, timezone, timezone, int(enabled), success, failure,
                 consecutive, score, cooldown, proxy_id),
            )
            connection.commit()

    def update_check_result_by_url(
        self, url: str, status: str, latency_ms: int = 0, exit_ip: str = "",
        checked_at: str = "", error: str = "", location: str = "",
        country_code: str = "", timezone: str = "",
    ) -> None:
        current = next((item for item in self.list_all() if item.url == url), None)
        success, failure, consecutive, enabled, score, cooldown = self._pool_result(current, status, latency_ms, checked_at)
        with get_connection() as connection:
            connection.execute(
                """UPDATE proxies SET status=?, latency_ms=?, exit_ip=?,
                   last_checked_at=?, check_error=?,
                   location=CASE WHEN ? != '' THEN ? ELSE location END,
                   country_code=CASE WHEN ? != '' THEN ? ELSE country_code END,
                   geo_timezone=CASE WHEN ? != '' THEN ? ELSE geo_timezone END,
                   enabled=?, success_count=?, failure_count=?, consecutive_failures=?,
                   quality_score=?, cooldown_until=? WHERE url=?""",
                (status, latency_ms, exit_ip, checked_at, error, location, location,
                 country_code, country_code, timezone, timezone, int(enabled), success, failure,
                 consecutive, score, cooldown, url),
            )
            connection.commit()

    @staticmethod
    def _pool_result(current: ProxyRecord | None, status: str, latency_ms: int, checked_at: str) -> tuple[int, int, int, bool, int, str]:
        success = current.success_count if current else 0
        failure = current.failure_count if current else 0
        consecutive = current.consecutive_failures if current else 0
        enabled = current.enabled if current else True
        cooldown = current.cooldown_until if current else ""
        if status not in {"live", "dead"}:
            return success, failure, consecutive, enabled, current.quality_score if current else 0, cooldown
        if status == "live":
            success += 1; consecutive = 0; enabled = True; cooldown = ""
        elif status == "dead":
            failure += 1; consecutive += 1
            if consecutive >= 3:
                enabled = False
                base = datetime.fromisoformat(checked_at) if checked_at else datetime.utcnow()
                cooldown = (base + timedelta(minutes=30)).isoformat(timespec="seconds")
        attempts = success + failure
        reliability = success / attempts if attempts else 0.0
        speed = max(0.0, 1.0 - max(0, latency_ms - 100) / 1900) if status == "live" else 0.0
        score = round(reliability * 70 + speed * 30)
        return success, failure, consecutive, enabled, score, cooldown

    def set_enabled(self, proxy_id: str, enabled: bool) -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE proxies SET enabled=?, cooldown_until=CASE WHEN ? THEN '' ELSE cooldown_until END WHERE id=?",
                (int(enabled), int(enabled), proxy_id),
            )
            connection.commit()

    def best_available(self, country_code: str = "") -> ProxyRecord | None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        records = [
            item for item in self.list_all()
            if item.enabled and item.status == "live"
            and (not item.cooldown_until or item.cooldown_until <= now)
            and (not country_code or item.country_code.casefold() == country_code.casefold())
        ]
        return max(records, key=lambda item: (item.quality_score, -item.latency_ms), default=None)

    def due_for_check(self, cutoff: str) -> list[ProxyRecord]:
        now = datetime.utcnow().isoformat(timespec="seconds")
        return [
            item for item in self.list_all()
            if (item.enabled or not item.cooldown_until or item.cooldown_until <= now)
            and (not item.last_checked_at or item.last_checked_at <= cutoff)
        ]

    def delete(self, proxy_id: str) -> None:
        with get_connection() as connection:
            connection.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
            connection.commit()
