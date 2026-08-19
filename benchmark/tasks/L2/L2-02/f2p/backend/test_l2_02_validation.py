from datetime import date, timedelta

from conftest import column_id


def _todo(client):
    return column_id(client, "To Do")


def test_empty_title_rejected(client):
    r = client.post(f"/api/columns/{_todo(client)}/cards", json={"title": ""})
    assert r.status_code == 422


def test_whitespace_title_rejected(client):
    r = client.post(f"/api/columns/{_todo(client)}/cards", json={"title": "   "})
    assert r.status_code == 422


def test_overlong_title_rejected(client):
    r = client.post(f"/api/columns/{_todo(client)}/cards", json={"title": "x" * 121})
    assert r.status_code == 422


def test_title_is_stripped(client):
    r = client.post(f"/api/columns/{_todo(client)}/cards", json={"title": "  Trimmed  "})
    assert r.status_code == 201
    assert r.json()["title"] == "Trimmed"


def test_invalid_priority_rejected(client):
    r = client.post(f"/api/columns/{_todo(client)}/cards",
                    json={"title": "ok", "priority": "urgent"})
    assert r.status_code == 422


def test_malformed_due_date_rejected(client):
    r = client.post(f"/api/columns/{_todo(client)}/cards",
                    json={"title": "ok", "due_date": "not-a-date"})
    assert r.status_code == 422


def test_past_due_date_rejected(client):
    past = (date.today() - timedelta(days=1)).isoformat()
    r = client.post(f"/api/columns/{_todo(client)}/cards",
                    json={"title": "ok", "due_date": past})
    assert r.status_code == 422


def test_today_and_future_due_dates_accepted(client):
    for d in (date.today(), date.today() + timedelta(days=14)):
        r = client.post(f"/api/columns/{_todo(client)}/cards",
                        json={"title": "fine", "due_date": d.isoformat()})
        assert r.status_code == 201
