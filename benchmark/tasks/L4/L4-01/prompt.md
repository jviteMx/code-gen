Columns have an optional `wip_limit` (work-in-progress limit) that is currently stored
but never enforced. Enforce it across the card workflow in
`backend/app/services/cards.py`:

- Creating a card in a column, or moving a card **into** a column from another column,
  must fail when the column already holds `wip_limit` cards.
- The failure is HTTP 409 with a **structured** detail object:
  `{"error": "wip_limit_exceeded", "column_id": <id>, "wip_limit": <n>}`
- Each rejection is recorded in the activity log with action `wip_rejected`
  (entity_type `column`, entity_id the column id). Note that the per-request DB
  dependency (`get_db` in `backend/app/db.py`) only commits when the request
  succeeds — make sure the rejection entry persists even though the request
  fails with 409.
- Columns whose `wip_limit` is NULL are unlimited.
- Moving a card **within** the same column (reordering) never triggers the limit —
  the card is already in the column.

The seeded "In Progress" column has `wip_limit = 3` and 2 cards; "To Do" and "Done"
are unlimited.

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
