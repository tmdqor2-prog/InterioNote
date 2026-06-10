"""
v2.7.0 Q — 빠른 답변 템플릿 API.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import quick_replies_service

router = APIRouter(prefix="/api/quick-replies", tags=["quick-replies"])


@router.get("")
def list_all():
    return {"replies": quick_replies_service.list_replies()}


class ReplyRequest(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    category: Optional[str] = ""
    sort_order: int = 0


@router.post("")
def create(req: ReplyRequest):
    try:
        return quick_replies_service.create_reply(
            req.title, req.content, req.category, req.sort_order
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


class ReplyUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    sort_order: Optional[int] = None


@router.patch("/{reply_id}")
def update(reply_id: int, req: ReplyUpdateRequest):
    try:
        return quick_replies_service.update_reply(
            reply_id,
            title=req.title,
            content=req.content,
            category=req.category,
            sort_order=req.sort_order,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{reply_id}")
def delete(reply_id: int):
    quick_replies_service.delete_reply(reply_id)
    return {"ok": True}
