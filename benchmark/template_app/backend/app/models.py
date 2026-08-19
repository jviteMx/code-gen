"""Pydantic schemas for the API layer."""

from __future__ import annotations

from pydantic import BaseModel


class CardIn(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    due_date: str | None = None


class CardUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    due_date: str | None = None


class CardOut(BaseModel):
    id: int
    column_id: int
    title: str
    description: str
    priority: str
    due_date: str | None
    position: int


class ColumnIn(BaseModel):
    name: str
    wip_limit: int | None = None


class ColumnOut(BaseModel):
    id: int
    board_id: int
    name: str
    position: int
    wip_limit: int | None
    cards: list[CardOut] = []


class BoardIn(BaseModel):
    name: str


class BoardSummary(BaseModel):
    id: int
    name: str
    slug: str


class BoardOut(BaseModel):
    id: int
    name: str
    slug: str
    columns: list[ColumnOut] = []


class ActivityOut(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: int
    ts: str
