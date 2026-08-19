Add a column archive workflow so finished columns can be hidden without deleting data.
This spans the schema, service layer, and API:

1. Schema (`backend/app/schema.sql`): columns get an `archived` flag
   (`INTEGER NOT NULL DEFAULT 0`).
2. New endpoint `POST /api/columns/{id}/archive` → 200 with the column body; archiving
   an already-archived column is idempotent (still 200). Unknown column → 404. Each
   (non-idempotent) archive is recorded in the activity log as `column_archived`
   (entity_type `column`).
3. Column API responses include `archived: bool`.
4. `GET /api/boards/{id}` excludes archived columns entirely.
5. `GET /api/columns/{id}/cards` returns `[]` for an archived column by default;
   passing `include_archived=true` returns its cards again.

Creating cards in an archived column is still allowed (product decision — they'll show
up when the column is unarchived later; no unarchive endpoint yet).

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
