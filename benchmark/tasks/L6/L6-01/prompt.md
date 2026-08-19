Overdue cards need to stand out on the board. This is a frontend-only change
(`frontend/src/`); the API already exposes each card's `due_date` (ISO `YYYY-MM-DD`).

A card is overdue when its `due_date` is strictly before today (no due date = never
overdue). For overdue cards:

1. The card element (`.card`) additionally gets the class `card--overdue`.
2. `.card--overdue` is styled with a `3px solid #dc2626` **left** border.
3. The card shows a badge element with class `overdue-badge` and the exact text
   `OVERDUE`, next to the priority badge in the card's meta row.

Non-overdue cards must not get the class or the badge. Compute "today" in the browser
(`new Date()`), comparing dates only (ignore time of day).

---
Verify your work with `npm run build` in `frontend/` (the backend test suite
`python -m pytest backend/tests` must stay green too).
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
