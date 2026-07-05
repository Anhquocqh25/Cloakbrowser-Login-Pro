from __future__ import annotations

import json
from typing import Any

from database.db import get_connection
from models.profile import Profile


class MaintenanceRepository:
    def log(
        self,
        action: str,
        *,
        profile_id: str = "",
        profile_name: str = "",
        severity: str = "info",
        details: str = "",
    ) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO activity_logs
                    (timestamp, action, profile_id, profile_name, severity, details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (Profile.now_timestamp(), action, profile_id, profile_name, severity, details[:4000]),
            )
            connection.commit()

    def list_activity(self, limit: int = 1000) -> list[dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, timestamp, action, profile_id, profile_name, severity, details
                FROM activity_logs ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(limit, 10000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_activity(self) -> None:
        with get_connection() as connection:
            connection.execute("DELETE FROM activity_logs")
            connection.commit()

    def save_health(
        self,
        profile_id: str,
        profile_name: str,
        status: str,
        summary: str,
        details: dict[str, Any],
        timestamp: str,
    ) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO health_checks
                    (timestamp, profile_id, profile_name, status, summary, details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (timestamp, profile_id, profile_name, status, summary, json.dumps(details, ensure_ascii=False)),
            )
            connection.commit()

    def list_health(self, limit: int = 1000) -> list[dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, timestamp, profile_id, profile_name, status, summary, details
                FROM health_checks ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(limit, 10000)),),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            try:
                record["details"] = json.loads(record["details"] or "{}")
            except (TypeError, json.JSONDecodeError):
                record["details"] = {}
            records.append(record)
        return records

    def save_fingerprint_snapshot(
        self,
        profile_id: str,
        profile_name: str,
        kind: str,
        cloak_version: str,
        fingerprint_hash: str,
        status: str,
        data: dict[str, Any],
        differences: dict[str, Any],
        created_at: str,
    ) -> int:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fingerprint_snapshots
                    (profile_id, profile_name, created_at, kind, cloak_version,
                     fingerprint_hash, status, data_json, differences_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id, profile_name, created_at, kind, cloak_version,
                    fingerprint_hash, status, json.dumps(data, ensure_ascii=False, sort_keys=True),
                    json.dumps(differences, ensure_ascii=False, sort_keys=True),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_fingerprint_snapshots(self, profile_id: str | None = None, limit: int = 2000) -> list[dict[str, Any]]:
        query = """
            SELECT id, profile_id, profile_name, created_at, kind, cloak_version,
                   fingerprint_hash, status, data_json, differences_json
            FROM fingerprint_snapshots
        """
        params: list[Any] = []
        if profile_id:
            query += " WHERE profile_id = ?"
            params.append(profile_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(limit, 10000)))
        with get_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            for source, target in (("data_json", "data"), ("differences_json", "differences")):
                try:
                    record[target] = json.loads(record.pop(source) or "{}")
                except (TypeError, json.JSONDecodeError):
                    record[target] = {}
            records.append(record)
        return records

    def latest_baseline(self, profile_id: str) -> dict[str, Any] | None:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT id, profile_id, profile_name, created_at, kind, cloak_version,
                       fingerprint_hash, status, data_json, differences_json
                FROM fingerprint_snapshots
                WHERE profile_id = ? AND kind = 'baseline'
                ORDER BY id DESC LIMIT 1
                """,
                (profile_id,),
            ).fetchone()
        if not row:
            return None
        record = dict(row)
        record["data"] = json.loads(record.pop("data_json") or "{}")
        record["differences"] = json.loads(record.pop("differences_json") or "{}")
        return record
