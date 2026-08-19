The card listing endpoint `GET /api/columns/{id}/cards` needs composable filters for
the upcoming board search feature. Extend the service layer
(`backend/app/services/cards.py`) and the endpoint (`backend/app/routers/columns.py`)
with three optional query parameters, all combinable with each other and with the
existing `sort` parameter:

- `priority=<low|medium|high>` — only cards with exactly that priority
- `overdue=<true|false>` — `true`: only cards whose `due_date` is strictly before
  today; `false`: only cards that are NOT overdue (no due date counts as not overdue).
  Reuse `parse_due_date()` from `backend/app/utils/text.py`.
- `q=<text>` — case-insensitive substring match on the card title

Omitted parameters filter nothing. Result order is unchanged (position order, or
priority order when `sort=priority`).

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
