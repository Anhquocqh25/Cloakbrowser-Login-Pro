from __future__ import annotations

from database.db import get_connection
from models.bookmark import BookmarkRecord


class BookmarkRepository:
    def list_all(self) -> list[BookmarkRecord]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, title, url, folder, created_at FROM bookmarks ORDER BY folder, title COLLATE NOCASE"
            ).fetchall()
        return [BookmarkRecord.from_row(row) for row in rows]

    def save(self, record: BookmarkRecord) -> None:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO bookmarks (id, title, url, folder, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title, url=excluded.url,
                   folder=excluded.folder""",
                (record.id, record.title, record.url, record.folder, record.created_at),
            )
            connection.commit()

    def delete(self, bookmark_id: str) -> None:
        with get_connection() as connection:
            connection.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
            connection.commit()
