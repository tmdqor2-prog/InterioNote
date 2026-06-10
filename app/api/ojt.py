"""
v2.6.0 JJ — OJT 엑셀 동기화 API.

- GET  /api/ojt/config             : 현재 OJT 설정 (파일 경로, 매핑, 시트, 시작행)
- POST /api/ojt/config              : 설정 저장 (마법사 완료 후)
- POST /api/ojt/analyze             : 파일 첫 N 행 미리보기 (마법사용)
- GET  /api/ojt/preview/{meeting_id}: 동기화 미리보기 (실제 쓰기 전 확인)
- POST /api/ojt/sync/{meeting_id}   : 실제 동기화 (행 추가)
- GET  /api/ojt/fields              : InterioNote 가 제공하는 OJT 필드 목록
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.db import db_cursor
from app.services import ojt_service

router = APIRouter(prefix="/api/ojt", tags=["ojt"])


@router.get("/fields")
def list_fields():
    """InterioNote 가 OJT 에 채울 수 있는 필드 목록 (마법사용)."""
    return {
        "field_keys": config.OJT_FIELD_KEYS,
        "field_labels": config.OJT_FIELD_LABELS,
    }


@router.get("/config")
def get_config():
    cfg = ojt_service.get_config()
    return {
        "configured": ojt_service.is_configured(),
        **cfg,
    }


class ConfigSaveRequest(BaseModel):
    file_path: str = ""
    column_mapping: dict[str, Any] = Field(default_factory=dict)
    start_row: int = 2
    sheet_name: Optional[str] = None


@router.post("/config")
def save_config(req: ConfigSaveRequest):
    ojt_service.save_config(
        file_path=req.file_path,
        column_mapping=req.column_mapping,
        start_row=req.start_row,
        sheet_name=req.sheet_name,
    )
    return {"ok": True, "configured": ojt_service.is_configured()}


class AnalyzeRequest(BaseModel):
    file_path: str
    head_rows: int = 5


@router.post("/analyze")
def analyze_file(req: AnalyzeRequest):
    try:
        return ojt_service.analyze_file(req.file_path, head_rows=req.head_rows)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"파일 분석 실패: {type(e).__name__}: {e}")


@router.get("/preview/{meeting_id}")
def preview(meeting_id: int):
    """동기화 전 미리보기 — 어떤 데이터가 OJT 에 쓰일지 사용자에게 보여줌.

    v2.6.1: 검증 완화. 초도상담뿐 아니라 모든 미팅에서 동기화 가능 — 다만:
      - is_first_consult: 신규 고객의 첫 초도상담 (자동 노출 권장)
      - this_meeting_synced: 이 미팅이 이미 동기화됐는지
      - client_synced_meeting_ids: 같은 고객의 이미 동기화된 미팅 id 목록 (있으면 "이미 등록됨" 표시)
    """
    with db_cursor() as cur:
        m = cur.execute(
            "SELECT meeting_type, client_id, ojt_synced_at FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()
        if m is None:
            raise HTTPException(404, "meeting not found")
        # 같은 client 의 이전 상담이 있는지 = 신규 여부 판단
        prev_count = cur.execute(
            "SELECT COUNT(*) AS n FROM meetings WHERE client_id = ? AND id < ?",
            (m["client_id"], meeting_id),
        ).fetchone()["n"]
        # v2.6.1: 같은 client 의 이미 동기화된 미팅들
        synced_rows = cur.execute(
            "SELECT id, meeting_type, started_at, ojt_synced_at "
            "FROM meetings WHERE client_id = ? AND ojt_synced_at IS NOT NULL "
            "ORDER BY ojt_synced_at DESC",
            (m["client_id"],),
        ).fetchall()
        client_synced = [
            {
                "meeting_id": r["id"],
                "meeting_type": r["meeting_type"],
                "started_at": r["started_at"],
                "ojt_synced_at": r["ojt_synced_at"],
            }
            for r in synced_rows
        ]

    is_first_consult = (m["meeting_type"] == "초도상담") and (prev_count == 0)
    this_meeting_synced = bool(m["ojt_synced_at"])
    client_already_registered = len(client_synced) > 0

    try:
        data = ojt_service.build_row_data(meeting_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    cfg = ojt_service.get_config()
    return {
        "meeting_id": meeting_id,
        "meeting_type": m["meeting_type"],
        "is_first_consult": is_first_consult,
        "is_new_client": prev_count == 0,
        "already_synced_at": m["ojt_synced_at"],
        "this_meeting_synced": this_meeting_synced,
        "client_already_registered": client_already_registered,
        "client_synced_meetings": client_synced,
        "configured": ojt_service.is_configured(),
        "data": data,
        "field_labels": config.OJT_FIELD_LABELS,
        "current_mapping": cfg["column_mapping"],
        "current_file_path": cfg["file_path"],
    }


class SyncRequest(BaseModel):
    """사용자가 미리보기에서 데이터 직접 편집한 후 동기화 요청.

    v2.6.1: force / 검증 제거 — 모든 미팅에서 동기화 가능 (기존 고객 상담 다시 보기 포함).
    UI 가 '이미 등록됨' 안내 + '수정 재등록' 버튼으로 사용자 의도를 확실히 함.
    """
    data: Optional[dict[str, str]] = None


@router.post("/sync/{meeting_id}")
def sync_meeting(meeting_id: int, req: SyncRequest):
    if not ojt_service.is_configured():
        raise HTTPException(409, "OJT 가 설정되지 않았습니다. 설정 → OJT 연동 에서 파일과 매핑을 먼저 등록하세요.")

    # v2.6.1: meeting 존재만 확인. 검증 (초도상담/신규고객) 은 더 이상 강제하지 않음.
    with db_cursor() as cur:
        m = cur.execute(
            "SELECT id FROM meetings WHERE id = ?", (meeting_id,)
        ).fetchone()
        if m is None:
            raise HTTPException(404, "meeting not found")

    try:
        result = ojt_service.append_row_to_ojt(meeting_id, override_data=req.data)
        return result
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        # 파일 lock / permission
        raise HTTPException(423, str(e))
    except Exception as e:
        import traceback as _tb
        print(f"[ojt_sync] {type(e).__name__}: {e}\n{_tb.format_exc()}", flush=True)
        raise HTTPException(500, f"OJT 동기화 실패: {type(e).__name__}: {str(e)[:300]}")
