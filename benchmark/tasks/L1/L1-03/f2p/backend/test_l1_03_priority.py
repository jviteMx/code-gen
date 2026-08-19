from app.services.cards import sorted_by_priority

from conftest import column_id


def _priorities(cards):
    return [c["priority"] for c in cards]


def test_high_medium_low_order():
    cards = [{"priority": p} for p in ("low", "high", "medium", "low", "high")]
    assert _priorities(sorted_by_priority(cards)) == ["high", "high", "medium", "low", "low"]


def test_medium_before_low():
    cards = [{"priority": "low"}, {"priority": "medium"}]
    assert _priorities(sorted_by_priority(cards)) == ["medium", "low"]


def test_api_sort_param(client):
    todo = column_id(client, "To Do")
    got = [c["priority"] for c in
           client.get(f"/api/columns/{todo}/cards", params={"sort": "priority"}).json()]
    # seeded To Do: 1 high, 2 medium, 1 low
    assert got == ["high", "medium", "medium", "low"]
