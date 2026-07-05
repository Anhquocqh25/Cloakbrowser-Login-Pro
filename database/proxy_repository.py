from __future__ import annotations

from database.db import get_connection
from models.proxy import ProxyRecord


class ProxyRepository:
    def list_all(self) -> list[ProxyRecord]:
        with get_connection() as connection:
            rows = connection.execute(
                """SELECT id, name, url, location, notes, created_at, status, latency_ms,
                          exit_ip, last_checked_at, check_error, country_code, geo_timezone
                   FROM proxies ORDER BY name COLLATE NOCASE"""
            ).fetchall()
        return [ProxyRecord.from_row(row) for row in rows]

    def get(self, proxy_id: str) -> ProxyRecord | None:
        with get_connection() as connection:
            row = connection.execute(
                """SELECT id, name, url, location, notes, created_at, status, latency_ms,
                          exit_ip, last_checked_at, check_error, country_code, geo_timezone FROM proxies WHERE id = ?""", (proxy_id,)
            ).fetchone()
        return ProxyRecord.from_row(row) if row else None

    def save(self, record: ProxyRecord) -> None:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO proxies (
                       id, name, url, location, notes, created_at, status, latency_ms,
                       exit_ip, last_checked_at, check_error, country_code, geo_timezone
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, url=excluded.url,
                   location=excluded.location, notes=excluded.notes, status=excluded.status,
                   latency_ms=excluded.latency_ms, exit_ip=excluded.exit_ip,
                   last_checked_at=excluded.last_checked_at, check_error=excluded.check_error,
                   country_code=excluded.country_code, geo_timezone=excluded.geo_timezone""",
                (
                    record.id, record.name, record.url, record.location, record.notes,
                    record.created_at, record.status, record.latency_ms, record.exit_ip,
                    record.last_checked_at, record.check_error,
                    record.country_code, record.timezone,
                ),
            )
            connection.commit()

    def update_check_result(
        self, proxy_id: str, status: str, latency_ms: int = 0, exit_ip: str = "",
        checked_at: str = "", error: str = "", location: str = "",
        country_code: str = "", timezone: str = "",
    ) -> None:
        with get_connection() as connection:
            connection.execute(
                """UPDATE proxies SET status=?, latency_ms=?, exit_ip=?,
                   last_checked_at=?, check_error=?,
                   location=CASE WHEN ? != '' THEN ? ELSE location END,
                   country_code=CASE WHEN ? != '' THEN ? ELSE country_code END,
                   geo_timezone=CASE WHEN ? != '' THEN ? ELSE geo_timezone END WHERE id=?""",
                (status, latency_ms, exit_ip, checked_at, error, location, location,
                 country_code, country_code, timezone, timezone, proxy_id),
            )
            connection.commit()

    def update_check_result_by_url(
        self, url: str, status: str, latency_ms: int = 0, exit_ip: str = "",
        checked_at: str = "", error: str = "", location: str = "",
        country_code: str = "", timezone: str = "",
    ) -> None:
        with get_connection() as connection:
            connection.execute(
                """UPDATE proxies SET status=?, latency_ms=?, exit_ip=?,
                   last_checked_at=?, check_error=?,
                   location=CASE WHEN ? != '' THEN ? ELSE location END,
                   country_code=CASE WHEN ? != '' THEN ? ELSE country_code END,
                   geo_timezone=CASE WHEN ? != '' THEN ? ELSE geo_timezone END WHERE url=?""",
                (status, latency_ms, exit_ip, checked_at, error, location, location,
                 country_code, country_code, timezone, timezone, url),
            )
            connection.commit()

    def delete(self, proxy_id: str) -> None:
        with get_connection() as connection:
            connection.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
            connection.commit()
