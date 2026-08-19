Card positions get messy: moving or deleting cards leaves gaps and duplicate position
values inside a column. Introduce a position-normalization module and wire it in.

1. Create a new module `backend/app/services/positions.py` exposing
   `normalize_column(conn, column_id)`: it re-packs the positions of all cards in that
   column to exactly `0, 1, 2, …, n-1`, preserving their current relative order
   (ties broken by card id).
2. Use it in `backend/app/services/cards.py`:
   - after `delete_card`, normalize the column the card was removed from
   - rework `move_card` so that when a `position` is given, the card is **inserted** at
     that index in the target column (cards at or after that index shift down one);
     when `position` is omitted, the card is appended at the end. After any move, both
     the source and target columns must be gapless (`0..n-1`).

Behavior that must not change: `create_card` still appends at the end; moving with no
`position` still appends.

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
