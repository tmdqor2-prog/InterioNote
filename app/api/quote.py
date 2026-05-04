"""
v2.8.0 FF — 견적서 자동 작성 API.

- GET  /api/quote/config             : 현재 견적서 설정
- POST /api/quote/config             : 설정 저장 (마법사 완료 후)
- POST /api/quote/analyze            : 템플릿 파일 시트/셀 미리보기
- GET  /api/quote/preview/{meeting_id}: 자동 채우기 미리보기 데이터
- POST /api/quote/generate/{meeting_id}: 실제 견적 초안 파일 생성
- GET  /api/quote/fields             : 견적서 필드 목록
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.services import quote_service

router = APIRouter(prefix="/api/quote", tags=["quote"])


@router.get("/fields")
def list_fields():
    return {
        "field_keys": config.QUOTE_FIELD_KEYS,
        "field_labels": config.QUOTE_FIELD_LABELS,
    }


@router.get("/config")
def get_config():
    cfg = quote_service.get_config()
    return {"configured": quote_service.is_configured(), **cfg}


class ConfigSaveRequest(BaseModel):
    template_path: str = ""
    template_name: str = ""
    cell_mapping: dict[str, Any] = Field(default_factory=dict)
    designer_name: str = ""


@router.post("/config")
def save_config(req: ConfigSaveRequest):
    quote_service.save_config(
        template_path=req.template_path,
        template_name=req.template_name,
        cell_mapping=req.cell_mapping,
        designer_name=req.designer_name,
    )
    return {"ok": True, "configured": quote_service.is_configured()}


class AnalyzeRequest(BaseModel):
    file_path: str


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    try:
        return quote_service.analyze_template(req.file_path)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"분석 실패: {type(e).__name__}: {e}")


@router.get("/preview/{meeting_id}")
def preview(meeting_id: int):
    cfg = quote_service.get_config()
    try:
        data = quote_service.build_quote_data(meeting_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "meeting_id": meeting_id,
        "configured": quote_service.is_configured(),
        "template_path": cfg["template_path"],
        "template_name": cfg["template_name"],
        "data": data,
        "field_labels": config.QUOTE_FIELD_LABELS,
        "field_keys": config.QUOTE_FIELD_KEYS,
    }


class GenerateRequest(BaseModel):
    data: Optional[dict[str, str]] = None


@router.post("/generate/{meeting_id}")
def generate(meeting_id: int, req: GenerateRequest):
    if not quote_service.is_configured():
        raise HTTPException(409, "견적서 양식이 설정되지 않았습니다. 설정 → 견적서 양식 에서 먼저 등록하세요.")
    try:
        return quote_service.generate_quote_draft(meeting_id, override_data=req.data)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(423, str(e))
    except Exception as e:
        import traceback as _tb
        print(f"[quote_generate] {type(e).__name__}: {e}\n{_tb.format_exc()}", flush=True)
        raise HTTPException(500, f"견적 초안 생성 실패: {type(e).__name__}: {str(e)[:300]}")
