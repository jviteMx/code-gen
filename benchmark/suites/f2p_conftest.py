"""Conftest injected alongside hidden F2P tests (mirrors the template's fixtures).

Copied into <trial>/backend/tests_f2p/conftest.py by the grader, so F2P tests
can use the same `conn` / `client` fixtures as the committed suite regardless
of what the agent did to backend/tests/.
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("KANBAN_DB", str(tmp_path / "svc.db"))
    from app import db
    db.init_db(seed=True)
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KANBAN_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("KANBAN_SEED", "1")
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c


def column_id(client_or_conn, name: str) -> int:
    if isinstance(client_or_conn, TestClient):
        board = client_or_conn.get("/api/boards/1").json()
        return next(c["id"] for c in board["columns"] if c["name"] == name)
    row = client_or_conn.execute("SELECT id FROM columns WHERE name = ?", (name,)).fetchone()
    return row["id"]
