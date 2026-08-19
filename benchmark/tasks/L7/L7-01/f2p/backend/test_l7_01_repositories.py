"""F2P: repository layer exists and services/routers are SQL-free."""

import re
from pathlib import Path

from conftest import BACKEND_DIR

SQL_CALL = re.compile(r"\.execute(script)?\s*\(")
SQL_KEYWORDS = re.compile(r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM)\b")


def test_repositories_package_exists():
    import app.repositories  # noqa: F401
    import app.repositories.activity  # noqa: F401
    import app.repositories.boards  # noqa: F401
    import app.repositories.cards  # noqa: F401


def test_repositories_contain_the_sql():
    repo_dir = Path(BACKEND_DIR) / "app" / "repositories"
    combined = "\n".join(p.read_text() for p in repo_dir.glob("*.py"))
    assert SQL_CALL.search(combined), "repositories must own the .execute() calls"
    assert SQL_KEYWORDS.search(combined), "repositories must own the SQL statements"


def test_services_are_sql_free():
    for f in (Path(BACKEND_DIR) / "app" / "services").glob("*.py"):
        src = f.read_text()
        assert not SQL_CALL.search(src), f"{f.name} still calls .execute()"
        assert not SQL_KEYWORDS.search(src), f"{f.name} still contains SQL"


def test_routers_are_sql_free():
    for f in (Path(BACKEND_DIR) / "app" / "routers").glob("*.py"):
        src = f.read_text()
        assert not SQL_CALL.search(src), f"{f.name} must not gain SQL"


def test_behavior_unchanged_via_api(client):
    board = client.get("/api/boards/1").json()
    assert sum(len(c["cards"]) for c in board["columns"]) == 8
    todo = next(c for c in board["columns"] if c["name"] == "To Do")
    created = client.post(f"/api/columns/{todo['id']}/cards", json={"title": "repo test"})
    assert created.status_code == 201
    moved = client.post(f"/api/cards/{created.json()['id']}/move",
                        params={"column_id": board["columns"][2]["id"]})
    assert moved.status_code == 200
    actions = [e["action"] for e in client.get("/api/activity?limit=100").json()]
    assert "card_created" in actions and "card_moved" in actions
