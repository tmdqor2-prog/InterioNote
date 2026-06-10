"""
v3.0.0 Phase 3 — 팔로업 템플릿 API.

팔로업 템플릿: 상담 종료 후 고객에게 보내는 메시지 초안.
변수: {{고객명}} {{담당자}} {{매장명}} {{날짜}} {{분석요약}}

- GET    /api/followup-templates            : 전체 목록 (meeting_type 필터 옵션)
- POST   /api/followup-templates            : 새 템플릿 생성
- PATCH  /api/followup-templates/{id}       : 수정
- DELETE /api/followup-templates/{id}       : 삭제
- POST   /api/followup-templates/{id}/render: 변수 치환 후 텍스트 반환
"""
from __future__ import annotations

import traceback
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.db import db_cursor, _DEFAULT_FOLLOWUP_TEMPLATES
from app.services import settings_service

router = APIRouter(prefix="/api/followup-templates", tags=["followup"])


def _describe_exc(prefix: str, e: Exception) -> str:
    print(f"\n[{prefix}] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
    return f"{type(e).__name__}: {str(e)[:400]}"


# ========================================
# 목록 조회
# ========================================
@router.get("")
def list_templates(meeting_type: Optional[str] = Query(None)):
    with db_cursor() as cur:
        if meeting_type:
            rows = cur.execute(
                "SELECT * FROM followup_templates WHERE meeting_type = ? AND is_active = 1 "
                "ORDER BY sort_order, id",
                (meeting_type,),
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT * FROM followup_templates WHERE is_active = 1 "
                "ORDER BY meeting_type, sort_order, id"
            ).fetchall()
    return [dict(r) for r in rows]


# ========================================
# 생성
# ========================================
class TemplateRequest(BaseModel):
    meeting_type: str = Field(..., description="'초도상담'|'디자인미팅'|'견적미팅'|'all'")
    title: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)
    sort_order: int = 0


@router.post("")
def create_template(req: TemplateRequest):
    try:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO followup_templates(meeting_type, title, content, sort_order) "
                "VALUES(?, ?, ?, ?)",
                (req.meeting_type, req.title.strip(), req.content.strip(), req.sort_order),
            )
            row_id = cur.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
            created = cur.execute(
                "SELECT * FROM followup_templates WHERE id = ?", (row_id,)
            ).fetchone()
    except Exception as e:
        raise HTTPException(500, _describe_exc("create_template", e))
    return dict(created)


# ========================================
# 수정
# ========================================
@router.patch("/{template_id}")
def update_template(template_id: int, req: TemplateRequest):
    try:
        with db_cursor() as cur:
            cur.execute(
                "UPDATE followup_templates SET meeting_type=?, title=?, content=?, "
                "sort_order=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (req.meeting_type, req.title.strip(), req.content.strip(),
                 req.sort_order, template_id),
            )
            row = cur.execute(
                "SELECT * FROM followup_templates WHERE id=?", (template_id,)
            ).fetchone()
    except Exception as e:
        raise HTTPException(500, _describe_exc("update_template", e))
    if row is None:
        raise HTTPException(404, "템플릿을 찾을 수 없습니다.")
    return dict(row)


# ========================================
# 삭제
# ========================================
@router.delete("/{template_id}")
def delete_template(template_id: int):
    with db_cursor() as cur:
        cur.execute("DELETE FROM followup_templates WHERE id=?", (template_id,))
    return {"ok": True}


# ========================================
# ⑫ v3.5.0: 기본 템플릿 추가 (없는 것만)
# ========================================
@router.post("/seed-defaults")
def seed_default_templates():
    """기본 제공 카카오 문구 템플릿을 추가합니다 (이미 같은 제목이 있으면 건너뜀)."""
    added = 0
    with db_cursor() as cur:
        existing_titles = {
            r["title"]
            for r in cur.execute("SELECT title FROM followup_templates").fetchall()
        }
        for meeting_type, title, content in _DEFAULT_FOLLOWUP_TEMPLATES:
            if title in existing_titles:
                continue
            cur.execute(
                "INSERT INTO followup_templates(meeting_type, title, content) "
                "VALUES(?, ?, ?)",
                (meeting_type, title, content),
            )
            added += 1
    return {"ok": True, "added": added}


# ========================================
# 변수 치환 렌더링
# meeting_id 와 meeting_type 을 기반으로 {{변수}} 치환 후 텍스트 반환
# ========================================
class RenderRequest(BaseModel):
    meeting_id: Optional[int] = None   # 상담 ID (고객명, 날짜, 분석요약 자동 추출용)
    overrides: Optional[dict] = None   # {"고객명": "홍길동", ...} 직접 지정 시


@router.post("/{template_id}/render")
def render_template(template_id: int, req: RenderRequest, request: Request):
    import re
    from datetime import datetime

    # 1) 템플릿 로드
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT * FROM followup_templates WHERE id=?", (template_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "템플릿을 찾을 수 없습니다.")
    content = row["content"]

    # 2) 변수 기본값 수집 — v3.5.2: 로그인 사용자별 담당자 정보
    _u = (getattr(request.state, "user", None) or {}).get("sub")
    designer = settings_service.get_designer_info(username=_u)
    vars_: dict = {
        "담당자": designer.get("name", ""),
        "매장명": designer.get("store", ""),
        "날짜": datetime.now().strftime("%Y-%m-%d"),
        "고객명": "",
        "분석요약": "",
    }

    # 3) meeting_id 있으면 DB 에서 보강
    if req.meeting_id:
        try:
            from app import config
            import json as _json
            with db_cursor() as cur:
                m_row = cur.execute(
                    "SELECT m.started_at, c.name AS client_name, a.data_json "
                    "FROM meetings m "
                    "JOIN clients c ON c.id = m.client_id "
                    "LEFT JOIN analyses a ON a.meeting_id = m.id "
                    "WHERE m.id = ?",
                    (req.meeting_id,),
                ).fetchone()
            if m_row:
                vars_["고객명"] = m_row["client_name"] or ""
                if m_row["started_at"]:
                    vars_["날짜"] = m_row["started_at"][:10]
                if m_row["data_json"]:
                    try:
                        data = _json.loads(m_row["data_json"])
                        vars_["분석요약"] = str(data.get("summary", "")).strip()
                    except Exception:
                        pass
        except Exception as e:
            print(f"[render_template] meeting 조회 실패: {e}", flush=True)

    # 4) overrides 병합
    if req.overrides and isinstance(req.overrides, dict):
        for k, v in req.overrides.items():
            vars_[k] = str(v)

    # 5) {{변수}} 치환
    def _replace(m: re.Match) -> str:
        key = m.group(1).strip()
        return vars_.get(key, m.group(0))  # 없는 변수는 그대로 유지

    rendered = re.sub(r"\{\{([^}]+)\}\}", _replace, content)

    return {"ok": True, "rendered": rendered, "vars": vars_}
