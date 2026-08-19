Column headers should show how many cards each column holds. Frontend-only change:

1. In each column header (`.column-header`, next to the column title), add a count
   chip: a `<span>` with class `count-chip` whose text is the number of cards
   currently in that column (seeded board: 4, 2, 2).
2. Style `.count-chip` as a pill in `frontend/src/styles/board.css`:
   - `border-radius` of at least 8px
   - a background color different from the column background (`#e2e8f0`)
   - visibly smaller text than the column title
3. The chip must update live: adding a card through the column's form increases that
   column's count without a page reload (the existing refresh flow already re-renders
   the board — just derive the count from the column's cards).

---
Verify your work with `npm run build` in `frontend/` (the backend test suite
`python -m pytest backend/tests` must stay green too).
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
