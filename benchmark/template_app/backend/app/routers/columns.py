"""Column endpoints."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..db import get_db
from ..models import CardOut, ColumnIn, ColumnOut
from ..services import boards as board_service
from ..services import cards as card_service

router = APIRouter()


@router.post("/boards/{board_id}/columns", response_model=ColumnOut, status_code=201)
def create_column(board_id: int, data: ColumnIn, conn: sqlite3.Connection = Depends(get_db)):
    return board_service.create_column(conn, board_id, data)


@router.put("/columns/{column_id}", response_model=ColumnOut)
def update_column(column_id: int, data: ColumnIn, conn: sqlite3.Connection = Depends(get_db)):
    return board_service.update_column(conn, column_id, data)


@router.delete("/columns/{column_id}", status_code=204)
def delete_column(column_id: int, conn: sqlite3.Connection = Depends(get_db)):
    board_service.delete_column(conn, column_id)


@router.get("/columns/{column_id}/cards", response_model=list[CardOut])
def list_cards(column_id: int, sort: str | None = None,
               conn: sqlite3.Connection = Depends(get_db)):
    return card_service.list_cards(conn, column_id, sort=sort)
