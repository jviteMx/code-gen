The column card listing needs pagination for large boards. Extend
`GET /api/columns/{column_id}/cards` (`backend/app/routers/columns.py`, and the
service in `backend/app/services/cards.py` as needed):

1. New optional query parameters:
   - `limit`: integer, default 50, minimum 1, maximum 200 — values outside the range
     are rejected with 422 (use FastAPI's `Query` constraints so the bounds appear in
     the OpenAPI schema)
   - `offset`: integer, default 0, minimum 0 — negative values rejected with 422
2. The response contains at most `limit` cards starting at `offset` (applied AFTER
   the existing `sort` handling, so pages are stable for a given sort).
3. Every response carries an `X-Total-Count` header: the total number of cards in the
   column BEFORE pagination.

Existing behavior for callers that pass nothing must be effectively unchanged
(default page of 50 covers all seeded columns).

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
