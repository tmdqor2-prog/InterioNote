"""
AI 분석 API (Phase 4).

- POST /api/meetings/{id}/analyze   : qwen 으로 분석 실행 (덮어쓰기)
- GET  /api/meetings/{id}/analysis  : 저장된 분석 결과 조회
- GET  /api/ollama/health           : Ollama + 모델 가용성 확인
"""
from __future__ import annotations

import traceback

from fastapi import APIRouter, HTTPException

from app import config
from app.services import analysis_service, ollama_client

router = APIRouter(tags=["analysis"])


def _describe_exc(prefix: str, e: Exception) -> str:
    print(f"\n[{prefix}] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
    return f"{type(e).__name__}: {str(e)[:400]}"


# ========================================
# Health
# ========================================
@router.get("/api/ollama/health")
def ollama_health():
    client = ollama_client.get_client()
    try:
        models = client.list_models()
    except ollama_client.OllamaError as e:
        return {
            "ok": False,
            "base_url": client.base_url,
            "configured_model": config.OLLAMA_MODEL,
            "error": str(e),
        }

    names = [m.get("name") for m in models if m.get("name")]
    return {
        "ok": True,
        "base_url": client.base_url,
        "configured_model": config.OLLAMA_MODEL,
        "model_ready": config.OLLAMA_MODEL in names,
        "installed_models": names,
    }


# ========================================
# Analyze
# ========================================
@router.post("/api/meetings/{meeting_id}/analyze")
def analyze_meeting(meeting_id: int):
    # 모델 가용성 체크 (친절한 에러 우선)
    client = ollama_client.get_client()
    try:
        models = client.list_models()
    except ollama_client.OllamaError as e:
        raise HTTPException(503, f"Ollama 연결 실패 — {e}")
    names = [m.get("name") for m in models if m.get("name")]
    if config.OLLAMA_MODEL not in names:
        raise HTTPException(
            409,
            f"모델 '{config.OLLAMA_MODEL}' 이(가) Ollama 에 없습니다. "
            f"설치된 모델: {names}. 'ollama pull {config.OLLAMA_MODEL}' 로 받아주세요.",
        )

    try:
        result = analysis_service.analyze_meeting(meeting_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ollama_client.OllamaError as e:
        raise HTTPException(502, f"Ollama 호출 실패 — {e}")
    except Exception as e:
        raise HTTPException(500, _describe_exc("analyze_meeting", e))

    return result


# ========================================
# Get existing analysis
# ========================================
@router.get("/api/meetings/{meeting_id}/analysis")
def get_analysis(meeting_id: int):
    existing = analysis_service.get_existing_analysis(meeting_id)
    if existing is None:
        return {"exists": False}
    return {"exists": True, **existing}
