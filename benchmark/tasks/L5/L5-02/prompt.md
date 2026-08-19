The card move endpoint takes its arguments as query parameters, which our API
guidelines forbid for mutations. Migrate it to a JSON body — a breaking contract
change:

1. `POST /api/cards/{card_id}/move` now takes a JSON body:
   `{"column_id": <int, required>, "position": <int or null, optional>}`
   (add a `CardMove` pydantic model in `backend/app/models.py`).
2. A missing body or missing `column_id` is rejected with 422 (query parameters must
   no longer be accepted).
3. Semantics are otherwise unchanged: unknown card or target column → 404, response is
   the moved card.
4. Update the frontend client (`moveCard` in `frontend/src/api.js`) to send the JSON
   body instead of query parameters.

---
Verify your work by running the test suite: `python -m pytest backend/tests` — note
that two existing move tests in `backend/tests/test_api_cards.py` cover the OLD
contract and are expected to fail after this change; the grader accounts for that.
Also run `npm run build` in `frontend/`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
