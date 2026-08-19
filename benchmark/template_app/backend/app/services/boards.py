"""Board operations: listing, detail assembly, creation."""

from __future__ import annotations

import sqlite3

from fastapi import HTTPException

from ..models import BoardIn, ColumnIn
from ..utils.text import slugify
from .activity import ActivityLog
from .cards import list_cards


def list_boards(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name, slug FROM boards ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_board(conn: sqlite3.Connection, board_id: int) -> dict:
    row = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="board not found")
    board = dict(row)
    cols = conn.execute(
        "SELECT * FROM columns WHERE board_id = ? ORDER BY position, id", (board_id,)
    ).fetchall()
    board["columns"] = [{**dict(c), "cards": list_cards(conn, c["id"])} for c in cols]
    return board


def create_board(conn: sqlite3.Connection, data: BoardIn) -> dict:
    slug = slugify(data.name)
    if conn.execute("SELECT 1 FROM boards WHERE slug = ?", (slug,)).fetchone():
        raise HTTPException(status_code=409, detail="a board with this name already exists")
    cur = conn.execute("INSERT INTO boards (name, slug) VALUES (?, ?)", (data.name, slug))
    ActivityLog(conn).record("board_created", "board", cur.lastrowid)
    return {**dict(conn.execute("SELECT * FROM boards WHERE id = ?", (cur.lastrowid,)).fetchone()),
            "columns": []}


def create_column(conn: sqlite3.Connection, board_id: int, data: ColumnIn) -> dict:
    get_board(conn, board_id)
    pos = conn.execute(
        "SELECT COALESCE(MAX(position) + 1, 0) FROM columns WHERE board_id = ?", (board_id,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO columns (board_id, name, position, wip_limit) VALUES (?, ?, ?, ?)",
        (board_id, data.name, pos, data.wip_limit),
    )
    ActivityLog(conn).record("column_created", "column", cur.lastrowid)
    row = conn.execute("SELECT * FROM columns WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {**dict(row), "cards": []}


def update_column(conn: sqlite3.Connection, column_id: int, data: ColumnIn) -> dict:
    row = conn.execute("SELECT * FROM columns WHERE id = ?", (column_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="column not found")
    conn.execute(
        "UPDATE columns SET name = ?, wip_limit = ? WHERE id = ?",
        (data.name, data.wip_limit, column_id),
    )
    ActivityLog(conn).record("column_updated", "column", column_id)
    updated = conn.execute("SELECT * FROM columns WHERE id = ?", (column_id,)).fetchone()
    return {**dict(updated), "cards": list_cards(conn, column_id)}


def delete_column(conn: sqlite3.Connection, column_id: int) -> None:
    row = conn.execute("SELECT * FROM columns WHERE id = ?", (column_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="column not found")
    conn.execute("DELETE FROM columns WHERE id = ?", (column_id,))
    ActivityLog(conn).record("column_deleted", "column", column_id)
