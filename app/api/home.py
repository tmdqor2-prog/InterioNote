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
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import config
from app.db import db_cursor
from app.services import settings_service, system_specs, quick_update_service, stage_service
from app.utils.folder_scanner import scan_clients
from app.utils.folder_template import check_template_status, ensure_client_template

router = APIRouter(prefix="/api", tags=["home"])


# ========================================
# Phase 8C: 시스템 사양 + 모델 추천
# 설정 페이지에서 사용자 PC 사양에 맞춰 동적으로 추천 배지 표시.
# ========================================
@router.get("/system/specs")
def get_system_specs():
    """CPU/RAM/GPU 감지 + Whisper 모델 추천 dict."""
    try:
        return system_specs.get_specs()
    except Exception as e:
        print(
            f"\n[system_specs] {type(e).__name__}: {e}\n{traceback.format_exc()}",
            flush=True,
        )
        # 사양 감지 실패해도 UI 가 죽지 않도록 안전한 fallback
        return {
            "platform": "unknown",
            "cpu_cores": None,
            "ram_gb": None,
            "gpu": None,
            "recommendation": {
                "realtime": "small",
                "post": "medium",
                "tier": "fallback",
                "note": f"사양 감지 실패 — small 권장. ({type(e).__name__})",
            },
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        }


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

    # v2.6.0 L+P / v3.0.0: DB 의 stage / is_favorite / last_meeting_at / 연락처 로 enrich
    if clients:
        from datetime import datetime as _dt
        today_str = _dt.now().strftime("%Y-%m-%d")
        limit_str = (_dt.now() + __import__("datetime").timedelta(days=60)).strftime("%Y-%m-%d")
        with db_cursor() as cur:
            rows = cur.execute(
                "SELECT id, folder_name, stage, is_favorite, last_meeting_at,"
                " phone, email, visit_source FROM clients"
            ).fetchall()
            db_by_folder = {r["folder_name"]: r for r in rows}
            # 각 고객의 다음 예정 일정 (가장 가까운 1건)
            appt_rows = cur.execute(
                """
                SELECT a.client_id, a.title, a.scheduled_at,
                  CAST((julianday(date(a.scheduled_at)) - julianday(date('now'))) AS INTEGER) as dday
                FROM appointments a
                WHERE a.completed = 0
                  AND date(a.scheduled_at) >= ?
                  AND date(a.scheduled_at) <= ?
                ORDER BY a.client_id, a.scheduled_at
                """,
                (today_str, limit_str),
            ).fetchall()
        next_appt_by_client = {}
        for ar in appt_rows:
            cid = ar["client_id"]
            if cid not in next_appt_by_client:
                next_appt_by_client[cid] = {
                    "title": ar["title"],
                    "scheduled_at": ar["scheduled_at"],
                    "dday": ar["dday"],
                }
        for c in clients:
            row = db_by_folder.get(c["folder_name"])
            if row:
                c["client_id"] = row["id"]
                c["stage"] = row["stage"] or config.CLIENT_STAGE_DEFAULT
                c["is_favorite"] = bool(row["is_favorite"])
                c["last_meeting_at"] = row["last_meeting_at"]
                c["phone"] = row["phone"]
                c["email"] = row["email"]
                c["visit_source"] = row["visit_source"]
                c["next_appointment"] = next_appt_by_client.get(row["id"])
            else:
                c["client_id"] = None
                c["stage"] = config.CLIENT_STAGE_DEFAULT
                c["is_favorite"] = False
                c["last_meeting_at"] = None
                c["phone"] = None
                c["email"] = None
                c["visit_source"] = None
                c["next_appointment"] = None

    return {
        "count": len(clients),
        "clients": clients,
        "root": str(client_root),
        "root_exists": client_root.exists(),
        "stages": config.CLIENT_STAGES,
    }


# ========================================
# v2.6.0 L+P — 진행 단계 / 즐겨찾기
# ========================================
class ClientStageRequest(BaseModel):
    stage: str


@router.post("/clients/{client_id}/stage")
def update_client_stage(client_id: int, req: ClientStageRequest):
    try:
        new_stage = stage_service.set_stage(client_id, req.stage)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"client_id": client_id, "stage": new_stage}


@router.post("/clients/{client_id}/favorite")
def toggle_client_favorite(client_id: int):
    new = stage_service.toggle_favorite(client_id)
    return {"client_id": client_id, "is_favorite": new}


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


@router.get("/app/lan-info")
def lan_info(request: Request):
    """v3.5.2: LAN IP + 포트 — QR 코드를 스마트폰이 접속 가능한 URL 로 만들기 위함.
    v3.5.3: 진단 정보(host_binding, firewall_likely_open) 도 추가.
    """
    import socket
    ip = "127.0.0.1"
    all_ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        pass
    # 모든 인터페이스의 IP 목록 (Tailscale + LAN + 가상)
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            cand = info[4][0]
            if cand and cand != "127.0.0.1" and cand not in all_ips:
                all_ips.append(cand)
    except Exception:
        pass
    if ip and ip != "127.0.0.1" and ip not in all_ips:
        all_ips.insert(0, ip)

    host_hdr = request.headers.get("host") or ""
    port = ""
    if ":" in host_hdr:
        port = host_hdr.rsplit(":", 1)[1]

    # 진단: 자체 LAN IP 로 본인 서버에 연결되는지 확인 (Windows 방화벽 통과 여부)
    firewall_test = None
    if port and ip != "127.0.0.1":
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ts:
                ts.settimeout(0.5)
                ts.connect((ip, int(port)))
                firewall_test = "ok"
        except Exception as e:
            firewall_test = f"blocked ({type(e).__name__})"

    return {
        "lan_ip": ip,
        "all_ips": all_ips,
        "port": port,
        "url_base": f"http://{ip}:{port}" if port else f"http://{ip}",
        "host_binding": "0.0.0.0 (LAN 노출)" if _server_listens_on_lan() else "127.0.0.1 (로컬 전용)",
        "firewall_test": firewall_test,
        "diag_hint": _diag_hint(ip, port, firewall_test),
    }


def _server_listens_on_lan() -> bool:
    """uvicorn 이 0.0.0.0 으로 떠 있는지 확인 (LAN 외부 접속 가능 여부)."""
    import socket
    # 실제 바인딩 확인 — 본인 LAN IP 로 별도 socket 연결 시도
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        my_ip = s.getsockname()[0]
        s.close()
        # LAN IP 와 127.0.0.1 가 다르면 0.0.0.0 으로 바인딩된 것 (정확하진 않지만 휴리스틱)
        return my_ip != "127.0.0.1"
    except Exception:
        return False


def _diag_hint(ip: str, port: str, firewall_test) -> str:
    """진단 결과 → 사용자가 볼 안내 문구."""
    if not port:
        return "포트 정보 없음"
    if ip == "127.0.0.1":
        return "LAN IP 가 감지되지 않습니다. WiFi 연결을 확인하세요."
    if firewall_test == "ok":
        return "정상 — 같은 WiFi 의 스마트폰에서 QR 스캔하면 열립니다."
    if firewall_test and firewall_test.startswith("blocked"):
        return (
            "Windows Defender 방화벽이 차단하고 있을 가능성이 높습니다. "
            "cmd 관리자 권한으로 다음 명령 실행하면 허용됩니다:\n"
            f"netsh advfirewall firewall add rule name=\"InterioNote LAN\" dir=in action=allow protocol=TCP localport={port}"
        )
    return "진단 미완료"


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


def _pick_quick_update_asset(assets: list) -> Optional[Dict[str, Any]]:
    """Phase 8D: Release 의 update zip 자산을 찾는다.
    이름이 'InterioNote-update-*.zip' 패턴이면 빠른 업데이트 패키지로 인식.
    반환: {url, name, size} 또는 None.
    """
    if not assets:
        return None
    for a in assets:
        name = (a.get("name") or "").lower()
        if name.startswith("interionote-update-") and name.endswith(".zip"):
            return {
                "url": a.get("browser_download_url"),
                "name": a.get("name"),
                "size": a.get("size"),
            }
    return None


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
    assets = data.get("assets") or []
    quick = _pick_quick_update_asset(assets)
    # 빠른 업데이트는 frozen build 에서만 의미
    quick_supported = bool(quick) and getattr(__import__("sys"), "frozen", False)
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
        "download_url": _pick_asset_url(assets),  # 인스톨러 (.exe)
        # Phase 8D: 빠른 업데이트 zip
        "quick_update": quick,                       # {url, name, size} or None
        "quick_update_supported": quick_supported,   # frozen 환경 + zip 자산 둘 다 있어야 True
    }


# ========================================
# Phase 8D — 인앱 빠른 업데이트
# ========================================
@router.get("/app/quick-update/status")
def quick_update_status():
    """현재 환경에서 빠른 업데이트 가능한지 + 직전 적용 결과."""
    return quick_update_service.quick_update_status()


@router.post("/app/quick-update/consume-marker")
def consume_quick_update_marker():
    """앱 시작 직후 토스트 표시용. 마커 읽고 삭제."""
    return {"marker": quick_update_service.consume_last_update_marker()}


class QuickUpdateRequest(BaseModel):
    download_url: str
    expected_version: str
    expected_sha256: Optional[str] = None


@router.post("/app/quick-update/run")
def run_quick_update(req: QuickUpdateRequest):
    """
    빠른 업데이트 풀 사이클 실행.
    성공 시 helper 가 백그라운드에서 시작되고, 약 1초 뒤 앱이 종료된다.
    helper 가 옛 InterioNote.exe 종료 대기 → 파일 교체 → 새 InterioNote.exe 재실행.
    """
    try:
        result = quick_update_service.perform_quick_update(
            download_url=req.download_url,
            expected_version=req.expected_version,
            expected_sha256=req.expected_sha256,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))  # 호환성 / manifest 오류
    except Exception as e:
        print(
            f"\n[quick_update] {type(e).__name__}: {e}\n{traceback.format_exc()}",
            flush=True,
        )
        raise HTTPException(500, f"빠른 업데이트 실패: {type(e).__name__}: {str(e)[:300]}")

    # 1초 뒤 앱 종료 트리거 (helper 가 종료 대기 중)
    quick_update_service.schedule_app_exit(delay_sec=1.0)
    return result


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
    # v3.0.0 Phase 1: 연락처
    phone: Optional[str] = None
    email: Optional[str] = None
    visit_source: Optional[str] = None  # 인스타그램, 지인소개, 블로그 등


class UpdateContactRequest(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None
    visit_source: Optional[str] = None


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
    phone_val = (req.phone or "").strip() or None
    email_val = (req.email or "").strip() or None
    visit_source_val = (req.visit_source or "").strip() or None
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO clients
                  (name, descriptor, folder_name, folder_path, first_met_at, phone, email, visit_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _sanitize_component(req.name),
                    descriptor_val,
                    folder_name,
                    str(folder_path),
                    first_met,
                    phone_val,
                    email_val,
                    visit_source_val,
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
        "phone": phone_val,
        "email": email_val,
        "visit_source": visit_source_val,
    }


# ========================================
# v3.0.0 Phase 1 — 고객 연락처 수정
# ========================================
@router.patch("/clients/{client_id}/contact")
def update_client_contact(client_id: int, req: UpdateContactRequest):
    """전화번호·이메일·방문경로 단독 수정 (customer.html 360뷰에서 사용)."""
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT id FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "고객을 찾을 수 없습니다.")
        cur.execute(
            """
            UPDATE clients
               SET phone = ?, email = ?, visit_source = ?
             WHERE id = ?
            """,
            (
                (req.phone or "").strip() or None,
                (req.email or "").strip() or None,
                (req.visit_source or "").strip() or None,
                client_id,
            ),
        )
    return {
        "client_id": client_id,
        "phone": (req.phone or "").strip() or None,
        "email": (req.email or "").strip() or None,
        "visit_source": (req.visit_source or "").strip() or None,
    }
