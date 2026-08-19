def test_stats_shape_and_values(client):
    r = client.get("/api/boards/1/stats")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"columns", "overdue_count"}
    cols = body["columns"]
    assert [(c["name"], c["card_count"]) for c in cols] == [
        ("To Do", 4), ("In Progress", 2), ("Done", 2)]
    # seeded overdue: -2 and -1 days in To Do, -7 and -3 days in Done
    assert body["overdue_count"] == 4


def test_stats_reflects_changes(client):
    board = client.get("/api/boards/1").json()
    todo = next(c for c in board["columns"] if c["name"] == "To Do")
    client.post(f"/api/columns/{todo['id']}/cards", json={"title": "extra"})
    stats = client.get("/api/boards/1/stats").json()
    counts = {c["name"]: c["card_count"] for c in stats["columns"]}
    assert counts["To Do"] == 5


def test_stats_unknown_board_404(client):
    assert client.get("/api/boards/999/stats").status_code == 404


def test_stats_documented_in_openapi(client):
    spec = client.get("/openapi.json").json()
    path = spec["paths"].get("/api/boards/{board_id}/stats")
    assert path is not None and "get" in path
    schema_ref = path["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema_ref  # a typed response model, not an empty schema
    assert schema_ref != {}
