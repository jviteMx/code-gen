Add a board statistics endpoint for dashboard widgets:

`GET /api/boards/{board_id}/stats` → HTTP 200 with exactly this shape:

```json
{
  "columns": [
    {"id": 1, "name": "To Do", "card_count": 4},
    {"id": 2, "name": "In Progress", "card_count": 2},
    {"id": 3, "name": "Done", "card_count": 2}
  ],
  "overdue_count": 4
}
```

- `columns` lists every column of the board in position order with its card count.
- `overdue_count` is the number of cards on the whole board whose `due_date` is
  strictly before today, regardless of column. Reuse `parse_due_date()` from
  `backend/app/utils/text.py`.
- Unknown board → 404.
- The endpoint must be properly typed with pydantic response models so it appears
  fully documented in the generated OpenAPI schema (`/openapi.json`) — the response
  schema is part of the graded contract.

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
