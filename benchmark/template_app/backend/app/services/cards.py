"""Card operations: CRUD, movement, and display ordering."""

from __future__ import annotations

import sqlite3

from fastapi import HTTPException

from ..models import CardIn, CardUpdate
from .activity import ActivityLog


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def get_card(conn: sqlite3.Connection, card_id: int) -> dict:
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="card not found")
    return _row_to_dict(row)


def list_cards(conn: sqlite3.Connection, column_id: int, sort: str | None = None) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM cards WHERE column_id = ? ORDER BY position, id", (column_id,)
    ).fetchall()
    cards = [_row_to_dict(r) for r in rows]
    if sort == "priority":
        cards = sorted_by_priority(cards)
    return cards


def sorted_by_priority(cards: list[dict]) -> list[dict]:
    """Order cards most-urgent first (high before medium before low)."""
    return sorted(cards, key=lambda c: c["priority"])


def create_card(conn: sqlite3.Connection, column_id: int, data: CardIn) -> dict:
    col = conn.execute("SELECT id FROM columns WHERE id = ?", (column_id,)).fetchone()
    if col is None:
        raise HTTPException(status_code=404, detail="column not found")
    pos = conn.execute(
        "SELECT COALESCE(MAX(position) + 1, 0) FROM cards WHERE column_id = ?", (column_id,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO cards (column_id, title, description, priority, due_date, position) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (column_id, data.title, data.description, data.priority, data.due_date, pos),
    )
    ActivityLog(conn).record("card_created", "card", cur.lastrowid)
    return get_card(conn, cur.lastrowid)


def update_card(conn: sqlite3.Connection, card_id: int, data: CardUpdate) -> dict:
    card = get_card(conn, card_id)
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE cards SET {sets} WHERE id = ?", (*fields.values(), card_id))
        ActivityLog(conn).record("card_updated", "card", card_id)
    return get_card(conn, card["id"])


def delete_card(conn: sqlite3.Connection, card_id: int) -> None:
    get_card(conn, card_id)
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    ActivityLog(conn).record("card_deleted", "card", card_id)


def move_card(conn: sqlite3.Connection, card_id: int, column_id: int, position: int | None = None) -> dict:
    get_card(conn, card_id)
    col = conn.execute("SELECT id FROM columns WHERE id = ?", (column_id,)).fetchone()
    if col is None:
        raise HTTPException(status_code=404, detail="column not found")
    if position is None:
        position = conn.execute(
            "SELECT COALESCE(MAX(position) + 1, 0) FROM cards WHERE column_id = ?", (column_id,)
        ).fetchone()[0]
    conn.execute(
        "UPDATE cards SET column_id = ?, position = ? WHERE id = ?",
        (column_id, position, card_id),
    )
    ActivityLog(conn).record("card_moved", "card", card_id)
    return get_card(conn, card_id)
