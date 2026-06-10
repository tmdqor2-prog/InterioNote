"""
v3.5.4 — 데이터 임포트 + 경로 마이그레이션 API.

- POST /api/import/preview    : 외부 폴더 스캔 미리보기
- POST /api/import/run        : 실제 임포트 실행
- POST /api/paths/preview     : 경로 마이그레이션 미리보기
- POST /api/paths/migrate     : 모든 경로를 현재 client_root 로 갱신
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services import audio_import_service, import_service, path_migration_service

router = APIRouter(tags=["import"])


# ─── 임포트 ──────────────────────────────────────────────────────────────────

class ImportRequest(BaseModel):
    root: str  # 임포트할 폴더 절대경로 (보통 SSD 안의 07_고객정보)


@router.post("/api/import/preview")
def import_preview(req: ImportRequest, request: Request):
    user = getattr(request.state, "user", None)
    if user is None or user.get("role") != "master":
        raise HTTPException(403, "마스터 권한이 필요합니다.")
    return import_service.preview(req.root)


@router.post("/api/import/run")
def import_run(req: ImportRequest, request: Request):
    user = getattr(request.state, "user", None)
    if user is None or user.get("role") != "master":
        raise HTTPException(403, "마스터 권한이 필요합니다.")
    try:
        return import_service.run(req.root)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")


# ─── 경로 마이그레이션 ────────────────────────────────────────────────────────

@router.post("/api/paths/preview")
def paths_preview(request: Request):
    user = getattr(request.state, "user", None)
    if user is None or user.get("role") != "master":
        raise HTTPException(403, "마스터 권한이 필요합니다.")
    return path_migration_service.preview()


@router.post("/api/paths/migrate")
def paths_migrate(request: Request):
    user = getattr(request.state, "user", None)
    if user is None or user.get("role") != "master":
        raise HTTPException(403, "마스터 권한이 필요합니다.")
    try:
        return path_migration_service.migrate()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")


# ─── v3.5.5: 외부 음성 파일에서 새 상담 만들기 ────────────────────────────────

class AudioImportRequest(BaseModel):
    audio_path: str = Field(..., min_length=1)
    client_folder_name: str = Field(..., min_length=1)
    meeting_type: str = Field(..., pattern=r"^(초도상담|디자인미팅|견적미팅)$")
    started_at: Optional[str] = None  # ISO 형식, 없으면 파일 수정 시각


@router.post("/api/import/audio-file")
def import_audio_file(req: AudioImportRequest):
    """
    iPhone 등에서 녹음한 외부 음성 파일을 새 상담으로 등록.
    파일을 고객 폴더 안 상담기록 폴더로 복사 + DB 등록 + 상담정보.json 생성.
    그 후 재전사 화면으로 이동해 전사 시작.
    """
    try:
        return audio_import_service.import_audio_file(
            audio_path=req.audio_path,
            client_folder_name=req.client_folder_name,
            meeting_type=req.meeting_type,
            started_at=req.started_at,
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")
