from app.services.activity import ActivityLog


def test_newest_first(conn):
    log = ActivityLog(conn)
    log.record("first", "card", 1)
    log.record("second", "card", 2)
    log.record("third", "card", 3)
    actions = [e["action"] for e in log.recent(limit=10)]
    assert actions[0] == "third"
    assert actions.index("third") < actions.index("second") < actions.index("first")


def test_consecutive_duplicates_collapsed(conn):
    log = ActivityLog(conn)
    log.record("card_moved", "card", 7)
    log.record("card_moved", "card", 7)
    log.record("card_moved", "card", 7)
    log.record("card_created", "card", 8)
    entries = log.recent(limit=10)
    moved_7 = [e for e in entries if e["action"] == "card_moved" and e["entity_id"] == 7]
    assert len(moved_7) == 1


def test_non_adjacent_repeats_kept(conn):
    log = ActivityLog(conn)
    log.record("card_moved", "card", 7)
    log.record("card_created", "card", 8)
    log.record("card_moved", "card", 7)
    entries = [e for e in log.recent(limit=10) if e["entity_id"] in (7, 8)]
    assert [e["action"] for e in entries] == ["card_moved", "card_created", "card_moved"]


def test_different_entities_not_collapsed(conn):
    log = ActivityLog(conn)
    log.record("card_moved", "card", 1)
    log.record("card_moved", "card", 2)
    moved = [e for e in log.recent(limit=10) if e["action"] == "card_moved"]
    assert len(moved) >= 2


def test_limit_applies_after_collapsing(conn):
    log = ActivityLog(conn)
    for _ in range(5):
        log.record("spam", "card", 99)
    log.record("a", "card", 1)
    log.record("b", "card", 2)
    entries = log.recent(limit=3)
    assert len(entries) == 3
    assert [e["action"] for e in entries[:2]] == ["b", "a"]
