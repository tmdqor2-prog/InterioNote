"""
v3.5.4 — 데이터 임포트 + 경로 마이그레이션 API.

- POST /api/import/preview    : 외부 폴더 스캔 미리보기
- POST /api/import/run        : 실제 임포트 실행
- POST /api/paths/preview     : 경로 마이그레이션 미리보기
- POST /api/paths/migrate     : 모든 경로를 현재 client_root 로 갱신
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services import import_service, path_migration_service

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
