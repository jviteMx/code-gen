"""Activity feed: records what happened to boards, columns, and cards."""

from __future__ import annotations

import sqlite3


class ActivityLog:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(self, action: str, entity_type: str, entity_id: int) -> None:
        self.conn.execute(
            "INSERT INTO activity (action, entity_type, entity_id) VALUES (?, ?, ?)",
            (action, entity_type, entity_id),
        )

    def recent(self, limit: int = 20) -> list[dict]:
        """The most recent activity entries."""
        rows = self.conn.execute(
            "SELECT * FROM activity ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
