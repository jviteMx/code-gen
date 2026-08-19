"""Board and column API tests."""


def test_list_boards_has_seeded_board(client):
    boards = client.get("/api/boards").json()
    assert any(b["name"] == "Sprint Board" for b in boards)


def test_board_detail_structure(client):
    board = client.get("/api/boards/1").json()
    names = [c["name"] for c in board["columns"]]
    assert names == ["To Do", "In Progress", "Done"]
    assert sum(len(c["cards"]) for c in board["columns"]) == 8


def test_board_detail_unknown_404(client):
    assert client.get("/api/boards/999").status_code == 404


def test_create_board(client):
    r = client.post("/api/boards", json={"name": "Roadmap"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Roadmap"
    assert body["slug"] == "roadmap"
    assert body["columns"] == []


def test_create_duplicate_board_conflict(client):
    client.post("/api/boards", json={"name": "Twice"})
    assert client.post("/api/boards", json={"name": "Twice"}).status_code == 409


def test_create_column_appends(client):
    r = client.post("/api/boards/1/columns", json={"name": "Review"})
    assert r.status_code == 201
    col = r.json()
    assert col["name"] == "Review"
    assert col["position"] == 3  # after the three seeded columns


def test_update_column_rename_and_wip(client):
    col = client.post("/api/boards/1/columns", json={"name": "Temp"}).json()
    r = client.put(f"/api/columns/{col['id']}", json={"name": "QA", "wip_limit": 2})
    assert r.status_code == 200
    assert r.json()["name"] == "QA"
    assert r.json()["wip_limit"] == 2


def test_delete_column_cascades(client):
    board = client.get("/api/boards/1").json()
    done = next(c for c in board["columns"] if c["name"] == "Done")
    card_ids = [card["id"] for card in done["cards"]]
    assert client.delete(f"/api/columns/{done['id']}").status_code == 204
    for cid in card_ids:
        assert client.get(f"/api/cards/{cid}").status_code == 404


def test_delete_unknown_column_404(client):
    assert client.delete("/api/columns/999").status_code == 404


def test_activity_endpoint_lists_events(client):
    client.post("/api/boards", json={"name": "Tracked Board"})
    actions = [e["action"] for e in client.get("/api/activity?limit=100").json()]
    assert "board_created" in actions
