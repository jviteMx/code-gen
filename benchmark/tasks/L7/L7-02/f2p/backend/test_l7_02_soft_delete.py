from conftest import column_id


def _make(client, title="victim"):
    todo = column_id(client, "To Do")
    return client.post(f"/api/columns/{todo}/cards", json={"title": title}).json()


def test_soft_delete_keeps_row(client, tmp_path, monkeypatch):
    card = _make(client)
    assert client.delete(f"/api/cards/{card['id']}").status_code == 204
    # row must still exist in the DB, flagged deleted
    import os
    import sqlite3
    conn = sqlite3.connect(os.environ["KANBAN_DB"])
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card["id"],)).fetchone()
    conn.close()
    assert row is not None
    assert row["deleted"] == 1


def test_deleted_card_hidden_everywhere(client):
    card = _make(client, "hide me")
    client.delete(f"/api/cards/{card['id']}")
    assert client.get(f"/api/cards/{card['id']}").status_code == 404
    board = client.get("/api/boards/1").json()
    titles = [c["title"] for col in board["columns"] for c in col["cards"]]
    assert "hide me" not in titles
    col_cards = client.get(f"/api/columns/{card['column_id']}/cards").json()
    assert card["id"] not in [c["id"] for c in col_cards]


def test_restore_brings_card_back(client):
    card = _make(client, "phoenix")
    client.delete(f"/api/cards/{card['id']}")
    r = client.post(f"/api/cards/{card['id']}/restore")
    assert r.status_code == 200
    assert r.json()["title"] == "phoenix"
    assert client.get(f"/api/cards/{card['id']}").status_code == 200
    board = client.get("/api/boards/1").json()
    titles = [c["title"] for col in board["columns"] for c in col["cards"]]
    assert "phoenix" in titles


def test_restore_not_deleted_idempotent(client):
    card = _make(client)
    assert client.post(f"/api/cards/{card['id']}/restore").status_code == 200


def test_restore_unknown_card_404(client):
    assert client.post("/api/cards/424242/restore").status_code == 404


def test_deleted_listing_newest_first_capped(client):
    ids = []
    for i in range(7):
        card = _make(client, f"del {i}")
        client.delete(f"/api/cards/{card['id']}")
        ids.append(card["id"])
    listing = client.get("/api/cards/deleted").json()
    assert len(listing) == 5
    assert [c["title"] for c in listing] == [f"del {i}" for i in (6, 5, 4, 3, 2)]


def test_deleted_listing_custom_limit(client):
    for i in range(3):
        card = _make(client, f"lim {i}")
        client.delete(f"/api/cards/{card['id']}")
    assert len(client.get("/api/cards/deleted", params={"limit": 2}).json()) == 2


def test_restore_recorded_in_activity(client):
    card = _make(client)
    client.delete(f"/api/cards/{card['id']}")
    client.post(f"/api/cards/{card['id']}/restore")
    actions = [e["action"] for e in client.get("/api/activity?limit=100").json()]
    assert "card_restored" in actions


def test_column_delete_still_hard_deletes(client):
    board = client.get("/api/boards/1").json()
    done = next(c for c in board["columns"] if c["name"] == "Done")
    card_ids = [c["id"] for c in done["cards"]]
    client.delete(f"/api/columns/{done['id']}")
    for cid in card_ids:
        assert client.post(f"/api/cards/{cid}/restore").status_code == 404
