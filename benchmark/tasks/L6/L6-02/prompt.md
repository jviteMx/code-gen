The board is unusable on narrow screens: columns stay side-by-side and force
horizontal scrolling. Make the board responsive (frontend-only,
`frontend/src/styles/board.css`):

- At viewport widths **below 700px**: the board stacks its columns vertically
  (single column layout), each column stretches to the full available width, and the
  page no longer scrolls horizontally.
- At widths of 700px and above: the current horizontal row layout is unchanged
  (fixed 280px columns side by side).

Use a CSS media query; no JavaScript changes should be needed.

---
Verify your work with `npm run build` in `frontend/` (the backend test suite
`python -m pytest backend/tests` must stay green too).
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
