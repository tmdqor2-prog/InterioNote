"""
사용자 설정 API (Phase 5A).

- GET  /api/settings                         : 모든 현재 설정 + 선택지
- POST /api/settings/whisper                 : 모델 사이즈 + beam_size 변경
- POST /api/settings/vocab                   : 인테리어 키워드 사전 저장
- POST /api/settings/vocab/reset             : 키워드 기본값 복원
- POST /api/settings/noise-suppression       : 노이즈 제거 토글
- POST /api/settings/vad                     : VAD threshold 변경
"""
from __future__ import annotations

import traceback
from typing import Optional

from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services import settings_service, whisper_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _describe_exc(prefix: str, e: Exception) -> str:
    print(f"\n[{prefix}] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
    return f"{type(e).__name__}: {str(e)[:400]}"


# ========================================
# 전체 조회
# ========================================
@router.get("")
def get_settings(request: Request):
    # v3.5.2: 로그인 사용자별 designer 정보 자동 적용
    user = getattr(request.state, "user", None)
    username = user.get("sub") if user else None
    return settings_service.get_all_settings(username=username)


# ========================================
# Whisper
# ========================================
class WhisperSettingsRequest(BaseModel):
    model_size: Optional[str] = None
    beam_size: Optional[int] = Field(None, ge=1, le=8)
    device: Optional[str] = None  # Phase 8B: 'auto' | 'cpu' | 'cuda'


@router.post("/whisper")
def update_whisper_settings(req: WhisperSettingsRequest):
    changed = {}
    try:
        if req.model_size is not None:
            old = settings_service.get_whisper_model_size()
            if req.model_size != old:
                whisper_service.set_model_size(req.model_size)  # 모델 언로드 + 설정 저장
                changed["model_size"] = {"old": old, "new": req.model_size}
        if req.beam_size is not None:
            old_b = settings_service.get_whisper_beam_size()
            if int(req.beam_size) != old_b:
                settings_service.set_whisper_beam_size(int(req.beam_size))
                changed["beam_size"] = {"old": old_b, "new": int(req.beam_size)}
        if req.device is not None:
            old_d = settings_service.get_whisper_device()
            if req.device != old_d:
                settings_service.set_whisper_device(req.device)
                whisper_service.reset_models_for_device_change()
                changed["device"] = {"old": old_d, "new": req.device}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, _describe_exc("update_whisper", e))

    return {
        "ok": True,
        "changed": changed,
        "model_size": settings_service.get_whisper_model_size(),
        "beam_size": settings_service.get_whisper_beam_size(),
        "device": settings_service.get_whisper_device(),
        "loaded_in_memory": whisper_service.get_loaded_model_size(),
        "loaded_device": whisper_service.get_loaded_device(),
        "needs_warmup": (
            ("model_size" in changed or "device" in changed)
            and whisper_service.get_loaded_model_size() != settings_service.get_whisper_model_size()
        ),
    }


# ========================================
# 키워드 사전
# ========================================
class VocabRequest(BaseModel):
    text: str


@router.post("/vocab")
def update_vocab(req: VocabRequest):
    try:
        settings_service.set_interior_vocab(req.text)
    except Exception as e:
        raise HTTPException(500, _describe_exc("update_vocab", e))
    return {
        "ok": True,
        "interior_vocab": settings_service.get_interior_vocab(),
        "char_count": len(settings_service.get_interior_vocab()),
    }


@router.post("/vocab/reset")
def reset_vocab():
    settings_service.reset_interior_vocab()
    return {
        "ok": True,
        "interior_vocab": settings_service.get_interior_vocab(),
    }


# ========================================
# 노이즈 억제 토글
# ========================================
class NoiseRequest(BaseModel):
    enabled: bool


@router.post("/noise-suppression")
def update_noise_suppression(req: NoiseRequest):
    settings_service.set_noise_suppression_enabled(req.enabled)
    return {
        "ok": True,
        "enabled": settings_service.get_noise_suppression_enabled(),
    }


# ========================================
# VAD
# ========================================
class VadRequest(BaseModel):
    threshold: float = Field(..., ge=0.1, le=0.95)


@router.post("/vad")
def update_vad(req: VadRequest):
    try:
        settings_service.set_vad_threshold(req.threshold)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "threshold": settings_service.get_vad_threshold()}


# ========================================
# Paths — 고객 루트 (Phase 6A)
# ========================================
class ClientRootRequest(BaseModel):
    path: str
    create_if_missing: bool = False


@router.post("/client-root")
def update_client_root(req: ClientRootRequest):
    try:
        new_path = settings_service.set_client_root(req.path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, _describe_exc("set_client_root", e))

    exists = new_path.exists()
    created = False
    if not exists and req.create_if_missing:
        try:
            new_path.mkdir(parents=True, exist_ok=True)
            exists = True
            created = True
        except Exception as e:
            raise HTTPException(500, f"폴더 생성 실패: {type(e).__name__}: {e}")

    return {
        "ok": True,
        "path": str(new_path),
        "exists": exists,
        "created": created,
    }


# ========================================
# Paths — 폴더 템플릿 (Phase 6A)
# ========================================
class FolderTemplateRequest(BaseModel):
    folders: List[str]


@router.post("/folder-template")
def update_folder_template(req: FolderTemplateRequest):
    try:
        cleaned = settings_service.set_folder_template(req.folders)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, _describe_exc("set_folder_template", e))
    return {
        "ok": True,
        "folder_template": cleaned,
        "required_folder": settings_service.REQUIRED_FOLDER,
    }


@router.post("/folder-template/reset")
def reset_folder_template():
    """기본 템플릿으로 복원."""
    from app import config as _config

    cleaned = settings_service.set_folder_template(list(_config.FOLDER_TEMPLATE))
    return {"ok": True, "folder_template": cleaned}


# ========================================
# v3.0.0 — 담당자(디자이너) 정보
# ========================================
class DesignerInfoRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    store: Optional[str] = ""
    phone: Optional[str] = ""


def _username_of(request: Request) -> Optional[str]:
    user = getattr(request.state, "user", None)
    return user.get("sub") if user else None


@router.get("/designer")
def get_designer(request: Request):
    # v3.5.2: 로그인 사용자별 담당자 정보 (없으면 기존 글로벌 값 자동 폴백)
    return settings_service.get_designer_info(username=_username_of(request))


@router.post("/designer")
def update_designer(req: DesignerInfoRequest, request: Request):
    # v3.5.2: 로그인 사용자 전용 저장 — 다른 사용자 영향 없음
    try:
        info = settings_service.set_designer_info(
            name=req.name,
            store=req.store or "",
            phone=req.phone or "",
            username=_username_of(request),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **info}


# ========================================
# v3.0.0 Phase 3: Ollama 모델 선택
# ========================================
class OllamaModelRequest(BaseModel):
    model: str


@router.post("/ollama-model")
def update_ollama_model(req: OllamaModelRequest):
    try:
        settings_service.set_ollama_model(req.model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "model": settings_service.get_ollama_model()}


# ========================================
# v3.0.0 Phase 3: 분석 추가 항목 (상담 종류별)
# ========================================
class AnalysisExtraItemsRequest(BaseModel):
    meeting_type: str
    items: List[dict]


@router.get("/analysis-extra-items/{meeting_type}")
def get_analysis_extra_items(meeting_type: str):
    try:
        items = settings_service.get_analysis_extra_items(meeting_type)
    except Exception as e:
        raise HTTPException(500, _describe_exc("get_analysis_extra_items", e))
    return {"meeting_type": meeting_type, "items": items}


@router.post("/analysis-extra-items")
def update_analysis_extra_items(req: AnalysisExtraItemsRequest):
    try:
        result = settings_service.set_analysis_extra_items(req.meeting_type, req.items)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, _describe_exc("update_analysis_extra_items", e))
    return {"ok": True, "meeting_type": req.meeting_type, "items": result}
