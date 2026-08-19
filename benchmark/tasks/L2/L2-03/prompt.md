Improve the `ActivityLog` class in `backend/app/services/activity.py`:

1. `recent(limit)` must return entries **newest first** (it currently returns them
   oldest first).
2. Consecutive duplicate entries must be collapsed: when the same
   `(action, entity_type, entity_id)` appears multiple times in a row in the log,
   only one entry (the newest of the run) is kept. Non-adjacent repeats are NOT
   collapsed.
3. `limit` applies **after** collapsing, so the caller always gets up to `limit`
   distinct entries.

`record()` and the underlying table are unchanged.

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
