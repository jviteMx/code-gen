# Kanbanlite

A small kanban board app: FastAPI + SQLite backend, React (Vite) frontend.

## Layout

- `backend/app/` — FastAPI application
  - `routers/` — HTTP endpoints (mounted under `/api`)
  - `services/` — business logic (boards, cards, activity log)
  - `utils/` — small helpers
  - `db.py` / `schema.sql` — SQLite storage
- `backend/tests/` — pytest suite (`python -m pytest backend/tests`)
- `frontend/src/` — React components and styles (`npm run build` to bundle)

## Running

```bash
# API (serves frontend/dist statically if built)
uvicorn app.main:app --app-dir backend

# Tests
python -m pytest backend/tests

# Frontend bundle
cd frontend && npm run build
```

The database path comes from `KANBAN_DB` (default `backend/kanban.db`); a demo
board is seeded on first start.
