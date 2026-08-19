Add a `truncate(text: str, n: int) -> str` function to `backend/app/utils/text.py`
for shortening card titles in compact views.

Requirements:
- If `len(text) <= n`, return `text` unchanged.
- Otherwise return a shortened string ending in the single ellipsis character `…`
  (U+2026), whose total length (including the ellipsis) is at most `n`.
- Break at a word boundary: never cut a word in half. Drop the partial word and any
  trailing spaces before appending the ellipsis. If the text contains no space inside
  the cut window, a hard character cut is acceptable.

Examples:
- `truncate("hello", 10)` → `"hello"`
- `truncate("hello world again", 12)` → `"hello world…"`
- `truncate("hello world again", 9)` → `"hello…"`

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
