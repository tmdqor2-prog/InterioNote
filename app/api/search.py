"""
v2.8.0 통합 검색 API.

- GET  /api/search?q=...      : 통합 검색 (전사·메모·분석)
- GET  /api/search/status     : 인덱스 상태
- POST /api/search/reindex    : 재인덱싱 (수동 트리거)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services import search_service

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/status")
def status():
    return search_service.index_status()


@router.post("/reindex")
def reindex():
    try:
        counts = search_service.reindex_all()
        return {"ok": True, "counts": counts}
    except Exception as e:
        raise HTTPException(500, f"재인덱싱 실패: {type(e).__name__}: {str(e)[:200]}")


@router.get("")
def do_search(q: str = Query(..., min_length=1), limit: int = 50):
    return search_service.search(q, limit=limit)
