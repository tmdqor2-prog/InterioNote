"""
홈 화면 API.
- GET  /api/clients                     : 07_고객정보 폴더의 고객 목록
- GET  /api/meta                        : 상담 종류/경로 메타
- POST /api/clients/ensure-template     : 기존 고객 폴더 템플릿 보정
- POST /api/clients/new                 : 신규 고객 생성 (폴더 + DB)
"""
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.db import db_cursor
from app.services import settings_service
from app.utils.folder_scanner import scan_clients
from app.utils.folder_template import check_template_status, ensure_client_template

router = APIRouter(prefix="/api", tags=["home"])


# ========================================
# 공통 유틸
# ========================================
# Windows 파일명 금지 문자
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_component(s: str) -> str:
    """이름/괄호 내용에서 Windows 파일시스템 금지 문자 제거."""
    return _INVALID_CHARS.sub("", s).strip()


def _build_folder_name(name: str, descriptor: str) -> str:
    """'{name} 고객님({descriptor})' 또는 '{name} 고객님' 을 반환."""
    name = _sanitize_component(name)
    descriptor = _sanitize_component(descriptor)
    if not name:
        raise ValueError("이름이 비었거나 허용되지 않는 문자만 들어 있습니다.")
    if descriptor:
        return f"{name} 고객님({descriptor})"
    return f"{name} 고객님"


@router.get("/clients")
def list_clients():
    clients = scan_clients()
    client_root = settings_service.get_client_root()
    return {
        "count": len(clients),
        "clients": clients,
        "root": str(client_root),
        "root_exists": client_root.exists(),
    }


@router.get("/meta")
def meta():
    client_root = settings_service.get_client_root()
    return {
        "meeting_types": config.MEETING_TYPES,
        "client_root": str(client_root),
        "client_root_exists": client_root.exists(),
        "temp_recording_dir": str(config.TEMP_RECORDING_DIR),
        "folder_template": settings_service.get_folder_template(),
    }


@router.get("/app/info")
def app_info():
    """버전 정보 + 변경 이력 (시작 팝업, '정보' 메뉴에서 사용)."""
    return {
        "name": "InterioNote",
        "version": config.APP_VERSION,
        "changelog": config.CHANGELOG,
        "github_repo": (
            f"{config.GITHUB_OWNER}/{config.GITHUB_REPO}"
            if config.GITHUB_OWNER and config.GITHUB_REPO
            else None
        ),
    }


def _version_compare(a: str, b: str) -> int:
    """semver 비교 (major.minor.patch). a > b → 1, a < b → -1, == → 0."""
    def parts(v: str):
        v = (v or "").lstrip("vV").strip()
        out = []
        for x in v.split("."):
            num = ""
            for ch in x:
                if ch.isdigit():
                    num += ch
                else:
                    break
            out.append(int(num) if num else 0)
        return out
    pa, pb = parts(a), parts(b)
    while len(pa) < len(pb):
        pa.append(0)
    while len(pb) < len(pa):
        pb.append(0)
    if pa > pb:
        return 1
    if pa < pb:
        return -1
    return 0


def _pick_asset_url(assets: list) -> Optional[str]:
    """Release 의 .exe 자산 우선, 없으면 첫 자산. 없으면 None."""
    if not assets:
        return None
    for a in assets:
        n = (a.get("name") or "").lower()
        if n.endswith(".exe"):
            return a.get("browser_download_url")
    return assets[0].get("browser_download_url")


@router.get("/app/check-update")
def check_update():
    """
    GitHub Releases API 로 최신 버전을 조회하고 현재 APP_VERSION 과 비교.
    - 'is_latest': 최신/같은 버전이면 True
    - 'newer_available': 새 버전 발견 시 True
    - 'release_url': 다운로드 페이지 (브라우저로 열도록 안내)
    """
    if not config.GITHUB_OWNER or not config.GITHUB_REPO:
        return {
            "ok": False,
            "reason": "GitHub 저장소가 설정되지 않았습니다.",
            "current_version": config.APP_VERSION,
        }

    import httpx

    url = (
        f"https://api.github.com/repos/"
        f"{config.GITHUB_OWNER}/{config.GITHUB_REPO}/releases/latest"
    )
    try:
        r = httpx.get(
            url,
            timeout=10.0,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"InterioNote/{config.APP_VERSION}",
            },
        )
    except Exception as e:
        return {
            "ok": False,
            "reason": f"GitHub 접속 실패: {type(e).__name__}: {e}",
            "current_version": config.APP_VERSION,
        }

    if r.status_code == 404:
        return {
            "ok": True,
            "has_release": False,
            "current_version": config.APP_VERSION,
            "message": "아직 출시된 릴리스가 없습니다. (저장소는 정상)",
            "releases_url": (
                f"https://github.com/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/releases"
            ),
        }

    try:
        r.raise_for_status()
    except Exception as e:
        return {
            "ok": False,
            "reason": f"GitHub HTTP {r.status_code}: {str(e)[:200]}",
            "current_version": config.APP_VERSION,
        }

    data = r.json()
    tag = (data.get("tag_name") or "").strip()
    cmp = _version_compare(config.APP_VERSION, tag)
    return {
        "ok": True,
        "has_release": True,
        "current_version": config.APP_VERSION,
        "latest_version": tag.lstrip("vV"),
        "is_latest": cmp >= 0,
        "newer_available": cmp < 0,
        "release_name": data.get("name") or tag,
        "release_url": data.get("html_url"),
        "release_body": (data.get("body") or "")[:3000],
        "published_at": data.get("published_at"),
        "download_url": _pick_asset_url(data.get("assets") or []),
    }


class EnsureTemplateRequest(BaseModel):
    folder_name: str


def _resolve_client_folder(folder_name: str) -> Path:
    """
    사용자 입력 folder_name 이 CLIENT_ROOT 안쪽인지 안전 검증.
    path traversal (../) 차단.
    """
    if not folder_name or "\\" in folder_name or "/" in folder_name:
        raise HTTPException(status_code=400, detail="유효하지 않은 폴더 이름입니다.")
    client_root = settings_service.get_client_root()
    folder_path = (client_root / folder_name).resolve()
    try:
        folder_path.relative_to(client_root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="고객 루트 바깥의 폴더입니다.")
    if not folder_path.exists():
        raise HTTPException(status_code=404, detail=f"폴더를 찾을 수 없습니다: {folder_name}")
    return folder_path


@router.post("/clients/ensure-template")
def ensure_template(req: EnsureTemplateRequest):
    """기존 고객 폴더에 누락된 서브폴더를 자동 생성."""
    folder_path = _resolve_client_folder(req.folder_name)
    try:
        created = ensure_client_template(folder_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"폴더 생성 실패: {type(e).__name__}: {e}")

    status = check_template_status(folder_path)
    return {
        "folder_name": req.folder_name,
        "folder_path": str(folder_path),
        "created": created,
        "present": status["present"],
        "missing_after": status["missing"],  # 이론상 빈 배열이어야 함
    }


# ========================================
# 폴더명 미리보기 (실시간)
# ========================================
class PreviewRequest(BaseModel):
    name: str
    descriptor: Optional[str] = ""


@router.post("/clients/preview-folder-name")
def preview_folder_name(req: PreviewRequest):
    """신규 고객 생성 폼에서 '최종 폴더명' 미리보기."""
    try:
        folder_name = _build_folder_name(req.name or "", req.descriptor or "")
    except ValueError as e:
        return {"valid": False, "folder_name": "", "reason": str(e)}
    folder_path = settings_service.get_client_root() / folder_name
    return {
        "valid": True,
        "folder_name": folder_name,
        "folder_path": str(folder_path),
        "exists": folder_path.exists(),
    }


# ========================================
# 신규 고객 생성
# ========================================
class CreateClientRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    descriptor: Optional[str] = ""
    first_met_at: Optional[str] = None  # ISO date, 선택


@router.post("/clients/new")
def create_client(req: CreateClientRequest):
    """
    신규 고객 폴더 생성 + 6 서브폴더 생성 + clients 테이블 INSERT.
    """
    client_root = settings_service.get_client_root()
    if not client_root.exists():
        raise HTTPException(
            500,
            f"고객 루트 폴더를 찾을 수 없습니다: {client_root}",
        )

    try:
        folder_name = _build_folder_name(req.name, req.descriptor or "")
    except ValueError as e:
        raise HTTPException(400, str(e))

    folder_path = (client_root / folder_name).resolve()

    # path traversal 방어
    try:
        folder_path.relative_to(client_root.resolve())
    except ValueError:
        raise HTTPException(400, "고객 루트 바깥으로 벗어난 경로입니다.")

    if folder_path.exists():
        raise HTTPException(
            409,
            f"이미 존재하는 폴더입니다: {folder_name}. 기존 고객 목록에서 선택해 주세요.",
        )

    # 폴더 생성 + 템플릿 서브폴더
    try:
        folder_path.mkdir(parents=True, exist_ok=False)
        created_subs = ensure_client_template(folder_path)
    except Exception as e:
        print(f"\n[create_client:fs] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
        raise HTTPException(500, f"폴더 생성 실패: {type(e).__name__}: {e}")

    # DB insert
    descriptor_val = _sanitize_component(req.descriptor or "") or None
    first_met = req.first_met_at or datetime.now().date().isoformat()
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO clients (name, descriptor, folder_name, folder_path, first_met_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _sanitize_component(req.name),
                    descriptor_val,
                    folder_name,
                    str(folder_path),
                    first_met,
                ),
            )
            client_id = cur.lastrowid
    except Exception as e:
        # DB insert 실패하면 폴더도 롤백 (비어있을 때만)
        try:
            if folder_path.exists() and not any(
                (folder_path / sub).exists() and any((folder_path / sub).iterdir())
                for sub in settings_service.get_folder_template()
            ):
                import shutil
                shutil.rmtree(folder_path, ignore_errors=True)
        except Exception:
            pass
        print(f"\n[create_client:db] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
        raise HTTPException(500, f"DB 저장 실패: {type(e).__name__}: {e}")

    return {
        "client_id": client_id,
        "name": _sanitize_component(req.name),
        "descriptor": descriptor_val,
        "folder_name": folder_name,
        "folder_path": str(folder_path),
        "subfolders_created": created_subs,
        "first_met_at": first_met,
    }
