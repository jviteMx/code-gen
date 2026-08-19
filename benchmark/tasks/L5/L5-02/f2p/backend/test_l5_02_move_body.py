from conftest import column_id


def _card(client, col):
    return client.post(f"/api/columns/{col}/cards", json={"title": "mover"}).json()


def test_move_via_json_body(client):
    todo = column_id(client, "To Do")
    done = column_id(client, "Done")
    card = _card(client, todo)
    r = client.post(f"/api/cards/{card['id']}/move", json={"column_id": done})
    assert r.status_code == 200
    assert r.json()["column_id"] == done


def test_move_with_position_in_body(client):
    todo = column_id(client, "To Do")
    done = column_id(client, "Done")
    card = _card(client, todo)
    r = client.post(f"/api/cards/{card['id']}/move",
                    json={"column_id": done, "position": 0})
    assert r.status_code == 200


def test_missing_body_rejected(client):
    todo = column_id(client, "To Do")
    card = _card(client, todo)
    assert client.post(f"/api/cards/{card['id']}/move").status_code == 422


def test_missing_column_id_rejected(client):
    todo = column_id(client, "To Do")
    card = _card(client, todo)
    r = client.post(f"/api/cards/{card['id']}/move", json={"position": 1})
    assert r.status_code == 422


def test_query_params_no_longer_accepted(client):
    todo = column_id(client, "To Do")
    done = column_id(client, "Done")
    card = _card(client, todo)
    r = client.post(f"/api/cards/{card['id']}/move", params={"column_id": done})
    assert r.status_code == 422


def test_unknown_target_column_404(client):
    todo = column_id(client, "To Do")
    card = _card(client, todo)
    r = client.post(f"/api/cards/{card['id']}/move", json={"column_id": 999})
    assert r.status_code == 404


def test_frontend_client_sends_body():
    from pathlib import Path
    src = Path("frontend/src/api.js").read_text()
    move_fn = src[src.index("export function moveCard"):]
    move_fn = move_fn[:move_fn.index("export function", 10)] if "export function" in move_fn[10:] else move_fn
    assert "column_id" in move_fn
    assert "body" in move_fn and "JSON.stringify" in move_fn
    assert "URLSearchParams" not in move_fn
