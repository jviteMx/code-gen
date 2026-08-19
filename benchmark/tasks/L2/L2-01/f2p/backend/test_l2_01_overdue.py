from datetime import date, timedelta

from conftest import column_id


def _board_cards(client):
    board = client.get("/api/boards/1").json()
    return [card for col in board["columns"] for card in col["cards"]]


def test_past_due_card_is_overdue(client):
    cards = {c["title"]: c for c in _board_cards(client)}
    assert cards["Set up CI pipeline"]["is_overdue"] is True   # seeded 2 days overdue
    assert cards["Design landing page"]["is_overdue"] is True  # seeded 1 day overdue


def test_future_due_card_not_overdue(client):
    cards = {c["title"]: c for c in _board_cards(client)}
    assert cards["Write onboarding docs"]["is_overdue"] is False  # due in 5 days


def test_card_without_due_date_not_overdue(client):
    todo = column_id(client, "To Do")
    created = client.post(f"/api/columns/{todo}/cards", json={"title": "No deadline"}).json()
    assert created["is_overdue"] is False


def test_due_today_not_overdue(client):
    todo = column_id(client, "To Do")
    created = client.post(f"/api/columns/{todo}/cards",
                          json={"title": "Today", "due_date": date.today().isoformat()}).json()
    assert created["is_overdue"] is False


def test_single_card_endpoint_includes_field(client):
    todo = column_id(client, "To Do")
    created = client.post(
        f"/api/columns/{todo}/cards",
        json={"title": "Fetch me", "due_date": (date.today() + timedelta(days=3)).isoformat()},
    ).json()
    fetched = client.get(f"/api/cards/{created['id']}").json()
    assert fetched["is_overdue"] is False


def test_column_listing_includes_field(client):
    todo = column_id(client, "To Do")
    cards = client.get(f"/api/columns/{todo}/cards").json()
    assert all("is_overdue" in c for c in cards)
