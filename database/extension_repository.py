from __future__ import annotations

from database.db import get_connection
from models.extension import ExtensionRecord


class ExtensionRepository:
    def list_all(self) -> list[ExtensionRecord]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name, path, enabled, created_at FROM extensions ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [ExtensionRecord.from_row(row) for row in rows]

    def save(self, record: ExtensionRecord) -> None:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO extensions (id, name, path, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, path=excluded.path,
                   enabled=excluded.enabled""",
                (record.id, record.name, record.path, int(record.enabled), record.created_at),
            )
            connection.commit()

    def delete(self, extension_id: str) -> None:
        with get_connection() as connection:
            connection.execute("DELETE FROM extensions WHERE id = ?", (extension_id,))
            connection.commit()
