"""Card API tests."""

from conftest import column_id


def _future(days: int = 30) -> str:
    from datetime import date, timedelta
    return (date.today() + timedelta(days=days)).isoformat()


def test_create_card(client):
    todo = column_id(client, "To Do")
    r = client.post(f"/api/columns/{todo}/cards",
                    json={"title": "Ship it", "priority": "high", "due_date": _future()})
    assert r.status_code == 201
    assert r.json()["title"] == "Ship it"
    assert r.json()["priority"] == "high"


def test_create_card_unknown_column(client):
    assert client.post("/api/columns/999/cards", json={"title": "x"}).status_code == 404


def test_created_card_appears_on_board(client):
    todo = column_id(client, "To Do")
    created = client.post(f"/api/columns/{todo}/cards", json={"title": "Visible"}).json()
    board = client.get("/api/boards/1").json()
    todo_cards = next(c for c in board["columns"] if c["name"] == "To Do")["cards"]
    assert any(card["id"] == created["id"] for card in todo_cards)


def test_get_card_404(client):
    assert client.get("/api/cards/424242").status_code == 404


def test_patch_card(client):
    todo = column_id(client, "To Do")
    card = client.post(f"/api/columns/{todo}/cards", json={"title": "Old"}).json()
    r = client.patch(f"/api/cards/{card['id']}", json={"title": "New", "priority": "high"})
    assert r.status_code == 200
    assert r.json()["title"] == "New"
    assert r.json()["priority"] == "high"


def test_delete_card(client):
    todo = column_id(client, "To Do")
    card = client.post(f"/api/columns/{todo}/cards", json={"title": "Bye"}).json()
    assert client.delete(f"/api/cards/{card['id']}").status_code == 204
    assert client.get(f"/api/cards/{card['id']}").status_code == 404


def test_move_card_endpoint(client):
    todo = column_id(client, "To Do")
    done = column_id(client, "Done")
    card = client.post(f"/api/columns/{todo}/cards", json={"title": "Movable"}).json()
    r = client.post(f"/api/cards/{card['id']}/move", params={"column_id": done})
    assert r.status_code == 200
    assert r.json()["column_id"] == done


def test_move_card_unknown_target(client):
    todo = column_id(client, "To Do")
    card = client.post(f"/api/columns/{todo}/cards", json={"title": "Stuck"}).json()
    assert client.post(f"/api/cards/{card['id']}/move",
                       params={"column_id": 999}).status_code == 404


def test_list_column_cards_endpoint(client):
    todo = column_id(client, "To Do")
    cards = client.get(f"/api/columns/{todo}/cards").json()
    assert len(cards) == 4  # seeded To Do cards
    assert all(c["column_id"] == todo for c in cards)
