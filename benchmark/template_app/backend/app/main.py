"""Kanbanlite — a small kanban board API with a static frontend."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import boards, cards, columns


def create_app() -> FastAPI:
    app = FastAPI(title="Kanbanlite", version="0.1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(boards.router, prefix="/api")
    app.include_router(columns.router, prefix="/api")
    app.include_router(cards.router, prefix="/api")

    @app.on_event("startup")
    def _startup() -> None:
        init_db(seed=os.environ.get("KANBAN_SEED", "1") == "1")

    @app.exception_handler(OverflowError)
    def _overflow(request, exc):
        # ints beyond SQLite's 64-bit range would 500 deep in the DB layer;
        # reply with the standard HTTPValidationError shape
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": [], "msg": "integer out of range", "type": "value_error"}
        ]})

    static_dir = os.environ.get(
        "KANBAN_STATIC", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")
    )
    if Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


app = create_app()
