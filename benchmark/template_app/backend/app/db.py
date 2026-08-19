"""SQLite connection handling and schema/seed initialization."""

from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def db_path() -> str:
    return os.environ.get("KANBAN_DB", str(Path(__file__).resolve().parents[1] / "kanban.db"))


def connect() -> sqlite3.Connection:
    # FastAPI may enter and finalize generator dependencies on different worker
    # threads, so a request-scoped connection must be usable by either thread.
    conn = sqlite3.connect(db_path(), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(seed: bool = True) -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        if seed and conn.execute("SELECT COUNT(*) FROM boards").fetchone()[0] == 0:
            seed_demo(conn)
        conn.commit()
    finally:
        conn.close()


def seed_demo(conn: sqlite3.Connection) -> None:
    """Insert a demo board. Due dates are relative to today so overdue logic stays meaningful."""
    today = date.today()
    cur = conn.execute("INSERT INTO boards (name, slug) VALUES (?, ?)", ("Sprint Board", "sprint-board"))
    board_id = cur.lastrowid
    cols = {}
    for pos, (name, wip) in enumerate([("To Do", None), ("In Progress", 3), ("Done", None)]):
        cur = conn.execute(
            "INSERT INTO columns (board_id, name, position, wip_limit) VALUES (?, ?, ?, ?)",
            (board_id, name, pos, wip),
        )
        cols[name] = cur.lastrowid
    cards = [
        # (column, title, priority, due offset days from today, position)
        ("To Do", "Set up CI pipeline", "high", -2, 0),
        ("To Do", "Write onboarding docs", "low", 5, 1),
        ("To Do", "Refactor auth module", "medium", 2, 2),
        ("To Do", "Design landing page", "medium", -1, 3),
        ("In Progress", "Fix login redirect bug", "high", 1, 0),
        ("In Progress", "Add search endpoint", "medium", 4, 1),
        ("Done", "Bootstrap project skeleton", "low", -7, 0),
        ("Done", "Configure linters", "medium", -3, 1),
    ]
    for col, title, priority, offset, pos in cards:
        conn.execute(
            "INSERT INTO cards (column_id, title, priority, due_date, position) VALUES (?, ?, ?, ?, ?)",
            (cols[col], title, priority, (today + timedelta(days=offset)).isoformat(), pos),
        )
