"""
v2.7.0 Q — 빠른 답변 템플릿.

자주 쓰는 안내 문구 (자재 설명·공정 일정·AS 안내 등) 저장 + 클립보드.
DB 테이블 quick_replies 는 v2.6.0 에 이미 만들어져 있음.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db import db_cursor


def list_replies() -> list[dict[str, Any]]:
    with db_cursor() as cur:
        rows = cur.execute(
            "SELECT id, title, content, category, sort_order, created_at, updated_at "
            "FROM quick_replies ORDER BY category, sort_order, id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_reply(reply_id: int) -> dict[str, Any] | None:
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT * FROM quick_replies WHERE id = ?", (reply_id,)
        ).fetchone()
    return dict(row) if row else None


def create_reply(title: str, content: str, category: str | None = None,
                 sort_order: int = 0) -> dict[str, Any]:
    title = (title or "").strip()
    content = (content or "").strip()
    if not title:
        raise ValueError("제목은 비어있을 수 없습니다.")
    if not content:
        raise ValueError("내용은 비어있을 수 없습니다.")
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO quick_replies(title, content, category, sort_order) VALUES(?, ?, ?, ?)",
            (title[:80], content, (category or "").strip()[:40] or None, int(sort_order or 0)),
        )
        new_id = cur.lastrowid
    return get_reply(new_id) or {}


def update_reply(reply_id: int, *, title: str | None = None, content: str | None = None,
                 category: str | None = None, sort_order: int | None = None) -> dict[str, Any]:
    if not get_reply(reply_id):
        raise ValueError(f"reply {reply_id} not found")
    fields: list[str] = []
    params: list[Any] = []
    if title is not None:
        title = title.strip()
        if not title:
            raise ValueError("제목은 비어있을 수 없습니다.")
        fields.append("title = ?")
        params.append(title[:80])
    if content is not None:
        content = content.strip()
        if not content:
            raise ValueError("내용은 비어있을 수 없습니다.")
        fields.append("content = ?")
        params.append(content)
    if category is not None:
        fields.append("category = ?")
        params.append((category.strip()[:40]) or None)
    if sort_order is not None:
        fields.append("sort_order = ?")
        params.append(int(sort_order))
    if not fields:
        return get_reply(reply_id) or {}
    fields.append("updated_at = ?")
    params.append(datetime.now().isoformat(timespec="seconds"))
    params.append(reply_id)
    with db_cursor() as cur:
        cur.execute(
            f"UPDATE quick_replies SET {', '.join(fields)} WHERE id = ?",
            params,
        )
    return get_reply(reply_id) or {}


def delete_reply(reply_id: int) -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM quick_replies WHERE id = ?", (reply_id,))
