from conftest import column_id


def _fill(client, col, n):
    for i in range(n):
        client.post(f"/api/columns/{col}/cards", json={"title": f"card {i:02d}"})


def test_limit_and_offset(client):
    todo = column_id(client, "To Do")
    _fill(client, todo, 5)  # 4 seeded + 5 = 9 total
    r = client.get(f"/api/columns/{todo}/cards", params={"limit": 3, "offset": 0})
    assert r.status_code == 200
    assert len(r.json()) == 3
    r2 = client.get(f"/api/columns/{todo}/cards", params={"limit": 3, "offset": 8})
    assert len(r2.json()) == 1


def test_pages_do_not_overlap(client):
    todo = column_id(client, "To Do")
    _fill(client, todo, 5)
    page1 = client.get(f"/api/columns/{todo}/cards", params={"limit": 4, "offset": 0}).json()
    page2 = client.get(f"/api/columns/{todo}/cards", params={"limit": 4, "offset": 4}).json()
    ids1 = {c["id"] for c in page1}
    ids2 = {c["id"] for c in page2}
    assert not ids1 & ids2
    assert len(ids1 | ids2) == 8


def test_total_count_header(client):
    todo = column_id(client, "To Do")
    _fill(client, todo, 5)
    r = client.get(f"/api/columns/{todo}/cards", params={"limit": 2})
    assert r.headers.get("X-Total-Count") == "9"


def test_header_present_without_params(client):
    todo = column_id(client, "To Do")
    r = client.get(f"/api/columns/{todo}/cards")
    assert r.headers.get("X-Total-Count") == "4"
    assert len(r.json()) == 4


def test_limit_bounds_rejected(client):
    todo = column_id(client, "To Do")
    assert client.get(f"/api/columns/{todo}/cards", params={"limit": 0}).status_code == 422
    assert client.get(f"/api/columns/{todo}/cards", params={"limit": 201}).status_code == 422


def test_negative_offset_rejected(client):
    todo = column_id(client, "To Do")
    assert client.get(f"/api/columns/{todo}/cards", params={"offset": -1}).status_code == 422


def test_bounds_documented_in_openapi(client):
    spec = client.get("/openapi.json").json()
    params = spec["paths"]["/api/columns/{column_id}/cards"]["get"]["parameters"]
    by_name = {p["name"]: p for p in params}
    assert by_name["limit"]["schema"].get("maximum") == 200
    assert by_name["limit"]["schema"].get("minimum") == 1
    assert by_name["offset"]["schema"].get("minimum") == 0
