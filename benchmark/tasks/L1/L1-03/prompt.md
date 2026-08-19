Cards can be listed ordered by urgency via `GET /api/columns/{id}/cards?sort=priority`,
backed by `sorted_by_priority()` in `backend/app/services/cards.py`. Its docstring says
"high before medium before low", but it currently sorts the priority strings
alphabetically, which puts `medium` cards **after** `low` ones.

Fix `sorted_by_priority()` so cards order by urgency: all `high` cards first, then
`medium`, then `low`. Cards with an unknown priority value (if any) go last.

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
