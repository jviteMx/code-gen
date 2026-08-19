The `slugify()` function in `backend/app/utils/text.py` produces bad slugs: consecutive
non-alphanumeric characters each become their own hyphen, and slugs can start or end
with hyphens.

Fix `slugify()` so that:
- any run of consecutive non-alphanumeric characters collapses into a single hyphen
- the result never starts or ends with a hyphen

Examples: `"Hello,  World!"` → `"hello-world"`, `"  --Weird__Name--  "` → `"weird-name"`.
Existing behavior for already-clean input (`"Hello World"` → `"hello-world"`) must not change.

---
Verify your work by running the test suite: `python -m pytest backend/tests`.
Do not modify files under `backend/tests/`. Do not start long-running processes
(`npm run dev`, `uvicorn`, watch modes); they will hang and time out.
