"""
v2.8.0 통합 검색 (B + GG v0).

SQLite FTS5 기반 통합 검색 — 전사·메모·AI 분석을 모두 인덱싱.
"이전 상담에서 거실 색상 언급한 적 있던 고객" 같은 키워드 회수 가능.

설계 원칙:
- 별도 FTS5 가상 테이블 (transcript_search, notes_search, analysis_search)
- 원본 변경될 때마다 재인덱싱 (idempotent)
- 검색 결과: 매칭 카드/메모/분석 + 해당 client_id + meeting_id + 미리보기

진짜 의미 기반 RAG (sentence-transformers + chromadb) 는 v2.9.0 예정.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.db import db_cursor

# FTS5 스키마 — meeting_id 가 매핑되는 doc store + content table
_INIT_SQL = """
-- 전사 검색 (segment 단위)
CREATE VIRTUAL TABLE IF NOT EXISTS transcript_search USING fts5(
    text,
    meeting_id UNINDEXED,
    segment_id UNINDEXED,
    speaker UNINDEXED,
    start_ms UNINDEXED,
    tokenize='unicode61'
);

-- 메모 검색
CREATE VIRTUAL TABLE IF NOT EXISTS notes_search USING fts5(
    notes,
    meeting_id UNINDEXED,
    tokenize='unicode61'
);

-- AI 분석 검색 (summary + checklist + action_items 합본)
CREATE VIRTUAL TABLE IF NOT EXISTS analysis_search USING fts5(
    text,
    meeting_id UNINDEXED,
    tokenize='unicode61'
);
"""


def init_search_tables() -> None:
    """FTS5 테이블 보장."""
    with db_cursor() as cur:
        cur.executescript(_INIT_SQL)


def reindex_all() -> dict[str, int]:
    """전체 데이터를 FTS5 에 다시 인덱싱. 사용자가 수동 트리거 (또는 첫 사용 시)."""
    init_search_tables()
    counts = {"segments": 0, "notes": 0, "analyses": 0}
    with db_cursor() as cur:
        # 기존 인덱스 비움
        cur.execute("DELETE FROM transcript_search")
        cur.execute("DELETE FROM notes_search")
        cur.execute("DELETE FROM analysis_search")

        # 1) transcript_segments
        rows = cur.execute(
            "SELECT id, meeting_id, text, speaker, start_ms FROM transcript_segments WHERE text IS NOT NULL AND text != ''"
        ).fetchall()
        for r in rows:
            cur.execute(
                "INSERT INTO transcript_search(text, meeting_id, segment_id, speaker, start_ms) VALUES (?, ?, ?, ?, ?)",
                (r["text"], r["meeting_id"], r["id"], r["speaker"] or "", r["start_ms"]),
            )
        counts["segments"] = len(rows)

        # 2) meetings.notes
        rows = cur.execute(
            "SELECT id, notes FROM meetings WHERE notes IS NOT NULL AND notes != ''"
        ).fetchall()
        for r in rows:
            cur.execute(
                "INSERT INTO notes_search(notes, meeting_id) VALUES (?, ?)",
                (r["notes"], r["id"]),
            )
        counts["notes"] = len(rows)

        # 3) analyses
        rows = cur.execute("SELECT meeting_id, data_json FROM analyses").fetchall()
        for r in rows:
            try:
                a = json.loads(r["data_json"])
            except Exception:
                continue
            text_parts = []
            if isinstance(a, dict):
                if a.get("summary"):
                    text_parts.append(str(a["summary"]))
                for k in ("checklist", "checks", "action_items"):
                    v = a.get(k)
                    if isinstance(v, list):
                        text_parts.append(" ".join(str(x) for x in v))
                # site_info
                si = a.get("site_info") or {}
                if isinstance(si, dict):
                    text_parts.append(" ".join(f"{k}={v}" for k, v in si.items() if v))
            text = "\n".join(p for p in text_parts if p)
            if text:
                cur.execute(
                    "INSERT INTO analysis_search(text, meeting_id) VALUES (?, ?)",
                    (text, r["meeting_id"]),
                )
                counts["analyses"] += 1

    return counts


# FTS5 query 안전화 — 특수문자 제거, 한국어 다중 단어는 모두 매칭
_FTS_BAD = re.compile(r'["\'\(\)\*\?:\-]')


def _sanitize_query(q: str) -> str:
    q = _FTS_BAD.sub(" ", q.strip())
    parts = [p for p in q.split() if p]
    if not parts:
        return ""
    # 각 단어를 prefix 매칭 (한국어는 부분 일치 가능): "거실*" "색상*"
    return " ".join(p + "*" for p in parts)


def search(query: str, *, limit: int = 50) -> dict[str, Any]:
    """통합 검색.

    반환:
    {
      "query": "...",
      "total": int,
      "transcripts": [{meeting_id, segment_id, speaker, start_ms, text, snippet, client_name, started_at, meeting_type}],
      "notes": [{meeting_id, snippet, ...}],
      "analyses": [{meeting_id, snippet, ...}],
    }
    """
    init_search_tables()
    fts_q = _sanitize_query(query)
    out: dict[str, Any] = {
        "query": query,
        "fts_query": fts_q,
        "total": 0,
        "transcripts": [],
        "notes": [],
        "analyses": [],
    }
    if not fts_q:
        return out

    with db_cursor() as cur:
        # 1) 전사 검색 — snippet 으로 매칭 부분 강조
        rows = cur.execute(
            f"""
            SELECT t.text, t.meeting_id, t.segment_id, t.speaker, t.start_ms,
                   snippet(transcript_search, 0, '<mark>', '</mark>', '...', 16) AS snippet,
                   m.meeting_type, m.started_at,
                   c.name AS client_name, c.id AS client_id, c.descriptor
            FROM transcript_search t
            JOIN meetings m ON m.id = t.meeting_id
            JOIN clients c ON c.id = m.client_id
            WHERE transcript_search MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_q, limit),
        ).fetchall()
        out["transcripts"] = [dict(r) for r in rows]

        # 2) 메모 검색
        rows = cur.execute(
            f"""
            SELECT n.notes, n.meeting_id,
                   snippet(notes_search, 0, '<mark>', '</mark>', '...', 16) AS snippet,
                   m.meeting_type, m.started_at,
                   c.name AS client_name, c.id AS client_id, c.descriptor
            FROM notes_search n
            JOIN meetings m ON m.id = n.meeting_id
            JOIN clients c ON c.id = m.client_id
            WHERE notes_search MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_q, limit),
        ).fetchall()
        out["notes"] = [dict(r) for r in rows]

        # 3) AI 분석 검색
        rows = cur.execute(
            f"""
            SELECT a.text, a.meeting_id,
                   snippet(analysis_search, 0, '<mark>', '</mark>', '...', 16) AS snippet,
                   m.meeting_type, m.started_at,
                   c.name AS client_name, c.id AS client_id, c.descriptor
            FROM analysis_search a
            JOIN meetings m ON m.id = a.meeting_id
            JOIN clients c ON c.id = m.client_id
            WHERE analysis_search MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_q, limit),
        ).fetchall()
        out["analyses"] = [dict(r) for r in rows]

    out["total"] = len(out["transcripts"]) + len(out["notes"]) + len(out["analyses"])
    return out


def index_status() -> dict[str, int]:
    """현재 인덱스 통계 — UI 에 '재인덱싱 필요' 안내용."""
    init_search_tables()
    with db_cursor() as cur:
        idx_segs = cur.execute("SELECT COUNT(*) AS n FROM transcript_search").fetchone()["n"]
        idx_notes = cur.execute("SELECT COUNT(*) AS n FROM notes_search").fetchone()["n"]
        idx_analyses = cur.execute("SELECT COUNT(*) AS n FROM analysis_search").fetchone()["n"]
        # 실제 데이터
        actual_segs = cur.execute("SELECT COUNT(*) AS n FROM transcript_segments").fetchone()["n"]
        actual_notes = cur.execute("SELECT COUNT(*) AS n FROM meetings WHERE notes IS NOT NULL AND notes != ''").fetchone()["n"]
        actual_analyses = cur.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"]

    return {
        "indexed_segments": idx_segs,
        "indexed_notes": idx_notes,
        "indexed_analyses": idx_analyses,
        "actual_segments": actual_segs,
        "actual_notes": actual_notes,
        "actual_analyses": actual_analyses,
        "needs_reindex": (
            idx_segs != actual_segs
            or idx_notes != actual_notes
            or idx_analyses != actual_analyses
        ),
    }
