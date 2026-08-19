"""Board endpoints."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..db import get_db
from ..models import ActivityOut, BoardIn, BoardOut, BoardSummary
from ..services import boards as board_service
from ..services.activity import ActivityLog

router = APIRouter()


@router.get("/boards", response_model=list[BoardSummary])
def list_boards(conn: sqlite3.Connection = Depends(get_db)):
    return board_service.list_boards(conn)


@router.post("/boards", response_model=BoardOut, status_code=201)
def create_board(data: BoardIn, conn: sqlite3.Connection = Depends(get_db)):
    return board_service.create_board(conn, data)


@router.get("/boards/{board_id}", response_model=BoardOut)
def get_board(board_id: int, conn: sqlite3.Connection = Depends(get_db)):
    return board_service.get_board(conn, board_id)


@router.get("/activity", response_model=list[ActivityOut])
def recent_activity(limit: int = 20, conn: sqlite3.Connection = Depends(get_db)):
    return ActivityLog(conn).recent(limit)
