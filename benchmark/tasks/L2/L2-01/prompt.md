Card API responses should tell clients whether a card is overdue, so the frontend can
highlight it without re-implementing date logic.

Add a computed `is_overdue: bool` field to the card responses (`CardOut` in
`backend/app/models.py`):
- `true` when the card has a `due_date` that is strictly before today
- `false` when there is no `due_date`, or it is today or later

Every endpoint that returns cards (board detail, card CRUD, column card listing) must
include the field. Use the existing `parse_due_date()` helper from
`backend/app/utils/text.py` rather than parsing dates again.

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
