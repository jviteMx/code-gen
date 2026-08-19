Card creation currently accepts almost anything. Add validation to the `CardIn` model
in `backend/app/models.py` (pydantic v2 validators) so that invalid create requests are
rejected with HTTP 422:

- `title`: leading/trailing whitespace is stripped; after stripping it must be
  1–120 characters (empty or whitespace-only titles are rejected)
- `priority`: must be exactly one of `low`, `medium`, `high`
- `due_date`: when provided, must be a valid ISO date (`YYYY-MM-DD`) AND must not be
  in the past (today is allowed)

Only creation (`CardIn`) gets these rules — updating an existing card (`CardUpdate`)
is unchanged.

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
