The service layer mixes business logic with raw SQL, which blocks the planned move to
Postgres. Introduce a repository layer — an architecture refactor with **no behavior
change** (the entire existing test suite must stay green).

1. Create a package `backend/app/repositories/` containing `boards.py`, `cards.py`,
   and `activity.py`. All SQL currently living in `backend/app/services/` moves into
   repository functions (each takes the `conn` as its first argument).
2. After the refactor, **no file under `backend/app/services/` may call
   `.execute(` or build SQL strings** — services keep validation, HTTP errors,
   position/ordering logic decisions, and activity recording, but persistence goes
   through the repositories.
3. Don't move SQL up into the routers either — routers stay SQL-free.
4. `backend/app/db.py` (connection handling, schema, seeding) is out of scope and
   keeps its SQL.

Public service function signatures and API behavior are unchanged.

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
