from conftest import column_id


def _get(client, col, **params):
    return client.get(f"/api/columns/{col}/cards", params=params).json()


def test_filter_by_priority(client):
    todo = column_id(client, "To Do")
    cards = _get(client, todo, priority="high")
    assert [c["title"] for c in cards] == ["Set up CI pipeline"]


def test_filter_overdue_true(client):
    todo = column_id(client, "To Do")
    titles = {c["title"] for c in _get(client, todo, overdue="true")}
    assert titles == {"Set up CI pipeline", "Design landing page"}  # seeded -2 and -1 days


def test_filter_overdue_false(client):
    todo = column_id(client, "To Do")
    titles = {c["title"] for c in _get(client, todo, overdue="false")}
    assert titles == {"Write onboarding docs", "Refactor auth module"}


def test_no_due_date_counts_not_overdue(client):
    todo = column_id(client, "To Do")
    client.post(f"/api/columns/{todo}/cards", json={"title": "Dateless"})
    titles = {c["title"] for c in _get(client, todo, overdue="false")}
    assert "Dateless" in titles


def test_text_query_case_insensitive(client):
    todo = column_id(client, "To Do")
    assert [c["title"] for c in _get(client, todo, q="DOCS")] == ["Write onboarding docs"]
    assert [c["title"] for c in _get(client, todo, q="auth")] == ["Refactor auth module"]


def test_filters_compose(client):
    todo = column_id(client, "To Do")
    cards = _get(client, todo, priority="medium", overdue="true")
    assert [c["title"] for c in cards] == ["Design landing page"]


def test_no_params_returns_all(client):
    todo = column_id(client, "To Do")
    assert len(_get(client, todo)) == 4
