from conftest import column_id


def _fill_in_progress(client):
    """Seeded In Progress: wip_limit=3, 2 cards. Add one to reach the limit."""
    wip = column_id(client, "In Progress")
    r = client.post(f"/api/columns/{wip}/cards", json={"title": "Third card"})
    assert r.status_code == 201
    return wip


def test_create_within_limit_ok(client):
    _fill_in_progress(client)


def test_create_beyond_limit_409(client):
    wip = _fill_in_progress(client)
    r = client.post(f"/api/columns/{wip}/cards", json={"title": "Fourth card"})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "wip_limit_exceeded"
    assert detail["column_id"] == wip
    assert detail["wip_limit"] == 3


def test_move_into_full_column_409(client):
    wip = _fill_in_progress(client)
    todo = column_id(client, "To Do")
    card = client.get(f"/api/columns/{todo}/cards").json()[0]
    r = client.post(f"/api/cards/{card['id']}/move", params={"column_id": wip})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "wip_limit_exceeded"


def test_move_within_full_column_allowed(client):
    wip = _fill_in_progress(client)
    card = client.get(f"/api/columns/{wip}/cards").json()[0]
    r = client.post(f"/api/cards/{card['id']}/move",
                    params={"column_id": wip, "position": 2})
    assert r.status_code == 200


def test_unlimited_columns_unaffected(client):
    todo = column_id(client, "To Do")
    for i in range(6):
        assert client.post(f"/api/columns/{todo}/cards",
                           json={"title": f"bulk {i}"}).status_code == 201


def test_rejection_recorded_in_activity(client):
    wip = _fill_in_progress(client)
    client.post(f"/api/columns/{wip}/cards", json={"title": "Rejected"})
    entries = client.get("/api/activity?limit=100").json()
    assert any(e["action"] == "wip_rejected" and e["entity_id"] == wip for e in entries)
