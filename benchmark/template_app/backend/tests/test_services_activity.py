"""Activity log tests."""

from app.services.activity import ActivityLog


def test_record_appears_in_recent(conn):
    log = ActivityLog(conn)
    log.record("card_created", "card", 1)
    actions = [e["action"] for e in log.recent(limit=50)]
    assert "card_created" in actions


def test_recent_respects_limit(conn):
    log = ActivityLog(conn)
    for i in range(10):
        log.record(f"action_{i}", "card", i)
    assert len(log.recent(limit=5)) <= 5


def test_recent_entries_have_expected_fields(conn):
    log = ActivityLog(conn)
    log.record("column_updated", "column", 3)
    entry = log.recent(limit=50)[-1] if log.recent(limit=50) else None
    assert entry is not None
    for key in ("id", "action", "entity_type", "entity_id", "ts"):
        assert key in entry


def test_card_operations_are_recorded(conn):
    from app.models import CardIn
    from app.services import cards as card_service
    from conftest import column_id

    todo = column_id(conn, "To Do")
    card = card_service.create_card(conn, todo, CardIn(title="tracked"))
    card_service.delete_card(conn, card["id"])
    actions = {e["action"] for e in ActivityLog(conn).recent(limit=100)}
    assert {"card_created", "card_deleted"} <= actions
