"""Card endpoints."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..db import get_db
from ..models import CardIn, CardOut, CardUpdate
from ..services import cards as card_service

router = APIRouter()


@router.post("/columns/{column_id}/cards", response_model=CardOut, status_code=201)
def create_card(column_id: int, data: CardIn, conn: sqlite3.Connection = Depends(get_db)):
    return card_service.create_card(conn, column_id, data)


@router.get("/cards/{card_id}", response_model=CardOut)
def get_card(card_id: int, conn: sqlite3.Connection = Depends(get_db)):
    return card_service.get_card(conn, card_id)


@router.patch("/cards/{card_id}", response_model=CardOut)
def update_card(card_id: int, data: CardUpdate, conn: sqlite3.Connection = Depends(get_db)):
    return card_service.update_card(conn, card_id, data)


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: int, conn: sqlite3.Connection = Depends(get_db)):
    card_service.delete_card(conn, card_id)


@router.post("/cards/{card_id}/move", response_model=CardOut)
def move_card(card_id: int, column_id: int, position: int | None = None,
              conn: sqlite3.Connection = Depends(get_db)):
    return card_service.move_card(conn, card_id, column_id, position)
