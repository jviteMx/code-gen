"""Card service tests (direct against the service layer)."""

import pytest
from fastapi import HTTPException

from app.models import CardIn, CardUpdate
from app.services import cards as card_service

from conftest import column_id


def test_create_card_appends_position(conn):
    todo = column_id(conn, "To Do")
    card = card_service.create_card(conn, todo, CardIn(title="New task"))
    assert card["title"] == "New task"
    assert card["position"] == 4  # seeded To Do has 4 cards at positions 0-3
    assert card["priority"] == "medium"


def test_create_card_unknown_column(conn):
    with pytest.raises(HTTPException) as exc:
        card_service.create_card(conn, 9999, CardIn(title="x"))
    assert exc.value.status_code == 404


def test_get_card_roundtrip(conn):
    todo = column_id(conn, "To Do")
    created = card_service.create_card(conn, todo, CardIn(title="Read me back"))
    fetched = card_service.get_card(conn, created["id"])
    assert fetched["title"] == "Read me back"
    assert fetched["column_id"] == todo


def test_get_card_missing(conn):
    with pytest.raises(HTTPException) as exc:
        card_service.get_card(conn, 424242)
    assert exc.value.status_code == 404


def test_update_card_partial(conn):
    todo = column_id(conn, "To Do")
    card = card_service.create_card(conn, todo, CardIn(title="Before", priority="low"))
    updated = card_service.update_card(conn, card["id"], CardUpdate(title="After"))
    assert updated["title"] == "After"
    assert updated["priority"] == "low"  # untouched field survives


def test_delete_card_removes_it(conn):
    todo = column_id(conn, "To Do")
    card = card_service.create_card(conn, todo, CardIn(title="Doomed"))
    card_service.delete_card(conn, card["id"])
    with pytest.raises(HTTPException):
        card_service.get_card(conn, card["id"])


def test_move_card_changes_column(conn):
    todo = column_id(conn, "To Do")
    done = column_id(conn, "Done")
    card = card_service.create_card(conn, todo, CardIn(title="Shippable"))
    moved = card_service.move_card(conn, card["id"], done)
    assert moved["column_id"] == done


def test_move_card_unknown_column(conn):
    todo = column_id(conn, "To Do")
    card = card_service.create_card(conn, todo, CardIn(title="x"))
    with pytest.raises(HTTPException) as exc:
        card_service.move_card(conn, card["id"], 9999)
    assert exc.value.status_code == 404


def test_list_cards_ordered_by_position(conn):
    todo = column_id(conn, "To Do")
    cards = card_service.list_cards(conn, todo)
    assert [c["position"] for c in cards] == sorted(c["position"] for c in cards)


def test_list_cards_empty_column_after_deletes(conn):
    done = column_id(conn, "Done")
    for c in card_service.list_cards(conn, done):
        card_service.delete_card(conn, c["id"])
    assert card_service.list_cards(conn, done) == []
