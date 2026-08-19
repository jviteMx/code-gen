from app.models import CardIn
from app.services import cards as card_service

from conftest import column_id


def _positions(conn, col):
    return [r["position"] for r in conn.execute(
        "SELECT position FROM cards WHERE column_id = ? ORDER BY position, id", (col,)
    ).fetchall()]


def test_normalize_module_exists(conn):
    from app.services.positions import normalize_column
    todo = column_id(conn, "To Do")
    conn.execute("UPDATE cards SET position = position * 10 WHERE column_id = ?", (todo,))
    normalize_column(conn, todo)
    assert _positions(conn, todo) == [0, 1, 2, 3]


def test_delete_repacks_column(conn):
    todo = column_id(conn, "To Do")
    middle = conn.execute(
        "SELECT id FROM cards WHERE column_id = ? AND position = 1", (todo,)
    ).fetchone()["id"]
    card_service.delete_card(conn, middle)
    assert _positions(conn, todo) == [0, 1, 2]


def test_move_insert_at_index_shifts_others(conn):
    todo = column_id(conn, "To Do")
    done = column_id(conn, "Done")
    card = card_service.create_card(conn, todo, CardIn(title="Insert me"))
    card_service.move_card(conn, card["id"], done, position=0)
    rows = conn.execute(
        "SELECT id, position FROM cards WHERE column_id = ? ORDER BY position", (done,)
    ).fetchall()
    assert [r["position"] for r in rows] == [0, 1, 2]
    assert rows[0]["id"] == card["id"]


def test_move_leaves_source_gapless(conn):
    todo = column_id(conn, "To Do")
    done = column_id(conn, "Done")
    victim = conn.execute(
        "SELECT id FROM cards WHERE column_id = ? AND position = 1", (todo,)
    ).fetchone()["id"]
    card_service.move_card(conn, victim, done)
    assert _positions(conn, todo) == [0, 1, 2]


def test_move_without_position_appends(conn):
    todo = column_id(conn, "To Do")
    done = column_id(conn, "Done")
    card = card_service.create_card(conn, todo, CardIn(title="Append me"))
    moved = card_service.move_card(conn, card["id"], done)
    assert moved["position"] == 2  # Done had 2 seeded cards
    assert _positions(conn, done) == [0, 1, 2]


def test_move_within_same_column(conn):
    todo = column_id(conn, "To Do")
    last = conn.execute(
        "SELECT id FROM cards WHERE column_id = ? AND position = 3", (todo,)
    ).fetchone()["id"]
    card_service.move_card(conn, last, todo, position=0)
    rows = conn.execute(
        "SELECT id, position FROM cards WHERE column_id = ? ORDER BY position", (todo,)
    ).fetchall()
    assert rows[0]["id"] == last
    assert [r["position"] for r in rows] == [0, 1, 2, 3]
