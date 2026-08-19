Deleting a card is currently unrecoverable. Implement full-stack soft delete with
undo:

Backend:
1. Schema (`backend/app/schema.sql`): cards get a `deleted` flag
   (`INTEGER NOT NULL DEFAULT 0`).
2. `DELETE /api/cards/{card_id}` now soft-deletes: the row stays in the database with
   `deleted = 1`; the response stays 204. Soft-deleted cards disappear from the board
   detail, from column card listings, and `GET /api/cards/{card_id}` returns 404 for
   them. Deleting a column still hard-deletes its cards via the existing cascade.
3. New endpoint `POST /api/cards/{card_id}/restore` → 200 with the card body; it
   un-deletes a soft-deleted card (restoring a card that isn't deleted is an
   idempotent 200; a card id that doesn't exist at all is 404). Record activity
   `card_restored` (entity_type `card`).
4. New endpoint `GET /api/cards/deleted?limit=5` → the most recently deleted cards
   (newest deletion first, default limit 5). Mind FastAPI route ordering: this route
   must not be shadowed by `GET /api/cards/{card_id}`.

Frontend:
5. Each card gets a delete button (class `card-delete`) that calls the delete
   endpoint and refreshes the board.
6. Below the board, a "Recently deleted" section (element with class
   `recently-deleted`) lists the deleted cards' titles, each with a restore button
   (class `restore-btn`) that calls the restore endpoint and refreshes — the card
   reappears in its column. When nothing is deleted the section shows no cards.

---
Verify with `python -m pytest backend/tests` and `npm run build` in `frontend/`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
