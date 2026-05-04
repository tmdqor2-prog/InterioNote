"""
v2.6.0 K — 태그 시스템.

상담(meeting) 별 다중 태그. 디자이너가 자유 입력 + config.DEFAULT_TAG_SUGGESTIONS 자동완성.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.db import db_cursor

# 금지 문자 (특수문자 일부) — 보기 흉함 방지. # 은 사용자가 입력 시 자동 제거.
_FORBIDDEN = re.compile(r"[\s#,;|\\\/\"']+")


def normalize_tag(raw: str) -> str:
    """앞뒤 공백 제거, 내부 공백/금지문자를 _ 로 합쳐 단순화. 빈 문자열은 ''."""
    if not raw:
        return ""
    s = raw.strip().lstrip("#")
    s = _FORBIDDEN.sub("_", s)
    s = s.strip("_")
    return s[:32]  # 길이 제한


def list_tags_for_meeting(meeting_id: int) -> list[str]:
    with db_cursor() as cur:
        rows = cur.execute(
            "SELECT tag FROM meeting_tags WHERE meeting_id = ? ORDER BY created_at, tag",
            (meeting_id,),
        ).fetchall()
        return [r["tag"] for r in rows]


def set_tags_for_meeting(meeting_id: int, tags: Iterable[str]) -> list[str]:
    """전체 교체 (idempotent)."""
    cleaned: list[str] = []
    seen = set()
    for raw in tags:
        t = normalize_tag(raw)
        if not t or t in seen:
            continue
        seen.add(t)
        cleaned.append(t)

    with db_cursor() as cur:
        cur.execute("DELETE FROM meeting_tags WHERE meeting_id = ?", (meeting_id,))
        for t in cleaned:
            cur.execute(
                "INSERT INTO meeting_tags(meeting_id, tag) VALUES(?, ?)",
                (meeting_id, t),
            )
    return cleaned


def add_tag(meeting_id: int, raw: str) -> list[str]:
    t = normalize_tag(raw)
    if not t:
        return list_tags_for_meeting(meeting_id)
    with db_cursor() as cur:
        cur.execute(
            "INSERT OR IGNORE INTO meeting_tags(meeting_id, tag) VALUES(?, ?)",
            (meeting_id, t),
        )
    return list_tags_for_meeting(meeting_id)


def remove_tag(meeting_id: int, tag: str) -> list[str]:
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM meeting_tags WHERE meeting_id = ? AND tag = ?",
            (meeting_id, normalize_tag(tag)),
        )
    return list_tags_for_meeting(meeting_id)


def all_known_tags() -> list[str]:
    """현재 DB 에 사용된 모든 태그 (자동완성 후보)."""
    with db_cursor() as cur:
        rows = cur.execute(
            "SELECT tag, COUNT(*) AS n FROM meeting_tags GROUP BY tag ORDER BY n DESC, tag"
        ).fetchall()
        return [r["tag"] for r in rows]


def tags_for_client(client_id: int) -> list[str]:
    """한 고객의 모든 상담 태그 합집합 (정렬: 빈도)."""
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT mt.tag, COUNT(*) AS n
            FROM meeting_tags mt
            JOIN meetings m ON m.id = mt.meeting_id
            WHERE m.client_id = ?
            GROUP BY mt.tag
            ORDER BY n DESC, mt.tag
            """,
            (client_id,),
        ).fetchall()
        return [r["tag"] for r in rows]
