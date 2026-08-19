from conftest import column_id


def test_archive_endpoint_returns_column(client):
    done = column_id(client, "Done")
    r = client.post(f"/api/columns/{done}/archive")
    assert r.status_code == 200
    assert r.json()["archived"] is True


def test_archive_idempotent(client):
    done = column_id(client, "Done")
    client.post(f"/api/columns/{done}/archive")
    assert client.post(f"/api/columns/{done}/archive").status_code == 200


def test_archive_unknown_column_404(client):
    assert client.post("/api/columns/999/archive").status_code == 404


def test_board_excludes_archived_columns(client):
    done = column_id(client, "Done")
    client.post(f"/api/columns/{done}/archive")
    board = client.get("/api/boards/1").json()
    assert [c["name"] for c in board["columns"]] == ["To Do", "In Progress"]


def test_unarchived_columns_report_false(client):
    board = client.get("/api/boards/1").json()
    assert all(c["archived"] is False for c in board["columns"])


def test_archived_column_cards_hidden_by_default(client):
    done = column_id(client, "Done")
    client.post(f"/api/columns/{done}/archive")
    assert client.get(f"/api/columns/{done}/cards").json() == []


def test_include_archived_shows_cards(client):
    done = column_id(client, "Done")
    client.post(f"/api/columns/{done}/archive")
    cards = client.get(f"/api/columns/{done}/cards",
                       params={"include_archived": "true"}).json()
    assert len(cards) == 2  # seeded Done cards


def test_archive_recorded_in_activity(client):
    done = column_id(client, "Done")
    client.post(f"/api/columns/{done}/archive")
    entries = client.get("/api/activity?limit=100").json()
    assert any(e["action"] == "column_archived" and e["entity_id"] == done
               for e in entries)
