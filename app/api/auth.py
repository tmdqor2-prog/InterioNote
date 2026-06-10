"""
v3.0.0 Phase 2 — 인증 API.
v3.3.0 Phase 5 — 자기 등록 추가.

POST /api/auth/login           : 로그인 → JWT 토큰 반환
GET  /api/auth/me              : 현재 로그인 사용자 정보 (토큰 검증용)
POST /api/auth/change-password : 본인 비밀번호 변경
POST /api/auth/register        : 회원가입 신청 (인증 불필요, 마스터 승인 후 로그인 가능)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services import auth_server_client, auth_service, ollama_client, settings_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ─── 요청/응답 모델 ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=100)
    new_password: str = Field(..., min_length=4, max_length=100)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=30, pattern=r"^[a-zA-Z0-9_]+$")
    display_name: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=4, max_length=100)


class OllamaRemoteRequest(BaseModel):
    """원격 Ollama URL 설정 요청. 빈 문자열 / null → 로컬 사용으로 복귀."""
    url: Optional[str] = Field(None, max_length=300)


class OllamaRemoteTestRequest(BaseModel):
    """연결 테스트 요청 (저장 전 검증용)."""
    url: str = Field(..., min_length=1, max_length=300)


# ─── 엔드포인트 ───────────────────────────────────────────────────────────────

@router.post("/login")
def login(req: LoginRequest):
    """아이디 + 비밀번호 검증 후 JWT 토큰 반환.
    v3.5.3: 로컬 실패 시 Auth Server (데스크톱) 에 위임.
    """
    user = auth_service.authenticate_user(req.username, req.password)
    if user is None:
        # 1) 이미 로컬에 pending 사용자가 있으면 그대로 안내
        local_status = auth_service.get_user_status(req.username)
        if local_status == "pending":
            raise HTTPException(401, "가입 승인 대기 중입니다. 관리자 승인 후 로그인하실 수 있습니다.")
        # 2) 로컬에 없거나 비밀번호 틀림 → Auth Server 에 시도
        if auth_server_client.is_configured():
            try:
                user_data = auth_server_client.remote_login(req.username, req.password)
                if user_data is not None:
                    # 동기화 완료 → 로컬에서 다시 인증 (이제 됨)
                    user = auth_service.authenticate_user(req.username, req.password)
            except auth_server_client.AuthServerError as e:
                # Auth Server 자체 호출 실패 (네트워크 등) → 로컬 결과 유지하면서 안내
                raise HTTPException(
                    401,
                    f"로컬 계정 정보가 없고 Auth Server 호출도 실패했습니다 — {e}. "
                    "데스크톱이 켜져 있고 같은 Tailscale 네트워크인지 확인하세요."
                )
        if user is None:
            # 그래도 없으면 → 자격 증명 오류
            if auth_server_client.is_configured():
                raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다 (Auth Server 확인 완료).")
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    token = auth_service.create_token(user)
    return {
        "token": token,
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
    }


@router.post("/register", status_code=201)
def register(req: RegisterRequest):
    """회원가입 신청 — 마스터 승인 후 로그인 가능 (인증 불필요 엔드포인트).
    v3.5.3: Auth Server 가 설정돼 있으면 데스크톱으로 위임 (한 곳에서 통합 관리).
    """
    # 1) 클라이언트 모드면 데스크톱(Auth Server) 으로 위임
    if auth_server_client.is_configured():
        try:
            auth_server_client.remote_register(req.username, req.display_name, req.password)
            return {
                "ok": True,
                "username": req.username,
                "message": "가입 신청이 완료되었습니다 (관리자 승인 후 로그인 가능).",
            }
        except ValueError as e:
            raise HTTPException(409, str(e))
        except auth_server_client.AuthServerError as e:
            raise HTTPException(
                503,
                f"Auth Server 호출 실패 — {e}. 데스크톱이 켜져 있는지 확인 후 다시 시도해 주세요."
            )
    # 2) 단독 PC 또는 Auth Server 자체 → 로컬 가입
    try:
        user = auth_service.register_user(req.username, req.display_name, req.password)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(500, f"가입 신청 실패: {type(e).__name__}: {str(e)[:200]}")
    return {
        "ok": True,
        "username": user["username"],
        "message": "가입 신청이 완료되었습니다. 관리자 승인 후 로그인하실 수 있습니다.",
    }


@router.get("/me")
def get_me(request: Request):
    """현재 토큰의 사용자 정보 반환 (클라이언트 측 토큰 유효성 검증용)."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "인증이 필요합니다.")
    # v3.5.2: 본인의 원격 Ollama URL 도 함께 (설정 화면 표시용)
    ollama_remote_url = auth_service.get_user_ollama_url(user["sub"])
    return {
        "username": user["sub"],
        "display_name": user["display_name"],
        "role": user["role"],
        "ollama_remote_url": ollama_remote_url or "",
    }


# ─── v3.5.2: 사용자별 원격 Ollama 설정 ────────────────────────────────────────

@router.patch("/me/ollama-remote")
def update_my_ollama_remote(req: OllamaRemoteRequest, request: Request):
    """본인 계정의 원격 Ollama URL 저장 (또는 제거)."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "인증이 필요합니다.")
    cleaned = (req.url or "").strip()
    if cleaned and not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise HTTPException(400, "URL 은 http:// 또는 https:// 로 시작해야 합니다.")
    auth_service.set_user_ollama_url(user["sub"], cleaned or None)
    return {
        "ok": True,
        "ollama_remote_url": cleaned or "",
        "message": "원격 Ollama 사용 시작" if cleaned else "로컬 Ollama 로 복귀했습니다.",
    }


@router.post("/me/ollama-remote/test")
def test_my_ollama_remote(req: OllamaRemoteTestRequest, request: Request):
    """저장 전 URL 연결 테스트 — Ollama 응답 + 모델 목록 반환."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "인증이 필요합니다.")
    return ollama_client.test_remote_url(req.url)


# ─── v3.5.3: 원격 데스크톱 상태 인디케이터 (마스터 헤더용) ────────────────────

@router.get("/me/remote-status")
def get_my_remote_status(request: Request):
    """현재 로그인한 마스터의 원격 데스크톱 연결 상태 — 헤더에 항상 표시.
    빠른 응답을 위해 짧은 타임아웃으로 ping 만 함.
    반환:
      - configured: 원격 설정 여부
      - connected:  실제로 닿는지
      - state: 'remote_ok' | 'remote_fail' | 'local_only'
      - reason: 실패 시 한국어 안내
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "인증이 필요합니다.")
    if user.get("role") != "master":
        return {"configured": False, "connected": False, "state": "local_only",
                "reason": "일반 사용자는 본인 PC 만 사용합니다."}
    url = auth_service.get_user_ollama_url(user["sub"])
    if not url:
        return {"configured": False, "connected": False, "state": "local_only",
                "reason": "원격 데스크톱이 설정되지 않았습니다 — 설정 → AI 분석 탭에서 설정 가능."}
    # 짧은 ping
    result = ollama_client.test_remote_url(url)
    if result.get("ok"):
        return {
            "configured": True,
            "connected": True,
            "state": "remote_ok",
            "url": url,
            "latency_ms": result.get("latency_ms"),
            "reason": f"데스크톱 연결됨 ({result.get('latency_ms')}ms)",
        }
    return {
        "configured": True,
        "connected": False,
        "state": "remote_fail",
        "url": url,
        "reason": result.get("error") or "연결 실패",
    }


# ─── v3.5.3: Auth Server (중앙 계정 관리) 설정 (마스터 전용) ──────────────────

class AuthServerEnableRequest(BaseModel):
    enabled: bool


class AuthServerClientRequest(BaseModel):
    """이 PC 가 클라이언트(노트북) 일 때 — 데스크톱 URL + API 키 입력."""
    url: str = Field("", max_length=300)
    api_key: str = Field("", max_length=200)


def _require_master(request: Request):
    user = getattr(request.state, "user", None)
    if user is None or user.get("role") != "master":
        raise HTTPException(403, "마스터 권한이 필요합니다.")
    return user


@router.get("/auth-server/state")
def get_auth_server_state(request: Request):
    """현재 PC 의 Auth Server 설정 상태 (서버 모드 + 클라이언트 설정 모두)."""
    _require_master(request)
    enabled = settings_service.get_auth_server_enabled()
    api_key = settings_service.get_auth_server_api_key() if enabled else ""
    # 이 PC 의 LAN IP + 포트 (노트북에서 입력할 URL 안내용)
    server_url_hint = ""
    if enabled:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            host_hdr = request.headers.get("host") or ""
            port = host_hdr.rsplit(":", 1)[1] if ":" in host_hdr else ""
            if ip and port:
                server_url_hint = f"http://{ip}:{port}"
        except Exception:
            pass
    return {
        # 서버 모드 (이 PC 가 데스크톱 역할)
        "server_enabled": enabled,
        "server_api_key": api_key,
        "server_url_hint": server_url_hint,  # v3.5.3: 노트북에 알려줄 URL
        # 클라이언트 설정 (이 PC 가 노트북 역할)
        "client_url": settings_service.get_auth_server_url(),
        "client_api_key_set": bool(settings_service.get_auth_server_client_api_key()),
        "client_configured": settings_service.is_auth_server_client(),
    }


@router.post("/auth-server/enable-server")
def enable_auth_server(req: AuthServerEnableRequest, request: Request):
    """이 PC 를 Auth Server 로 토글. 켜면 API 키 자동 생성."""
    _require_master(request)
    settings_service.set_auth_server_enabled(req.enabled)
    api_key = settings_service.get_auth_server_api_key() if req.enabled else ""
    return {
        "ok": True,
        "server_enabled": req.enabled,
        "server_api_key": api_key,
        "message": (
            "이 PC 가 Auth Server 로 동작합니다. 노트북에 URL + API 키를 입력하세요."
            if req.enabled
            else "Auth Server 모드 OFF — 이 PC 는 단독 동작합니다."
        ),
    }


@router.post("/auth-server/regenerate-key")
def regenerate_auth_server_key(request: Request):
    """API 키 새로 생성 (이전 키는 무효화)."""
    _require_master(request)
    new_key = settings_service.regenerate_auth_server_api_key()
    return {"ok": True, "server_api_key": new_key}


@router.patch("/auth-server/client")
def set_auth_server_client(req: AuthServerClientRequest, request: Request):
    """이 PC 가 클라이언트일 때 — Auth Server URL + API 키 저장."""
    _require_master(request)
    url = (req.url or "").strip()
    key = (req.api_key or "").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(400, "URL 은 http:// 또는 https:// 로 시작해야 합니다.")
    settings_service.set_auth_server_url(url)
    settings_service.set_auth_server_client_api_key(key)
    return {
        "ok": True,
        "client_url": url,
        "client_api_key_set": bool(key),
        "client_configured": bool(url and key),
        "message": (
            "원격 Auth Server 사용 시작 — 다음 로그인부터 데스크톱 계정으로 시도합니다."
            if url and key
            else "단독 모드로 복귀 — 로컬 계정만 사용합니다."
        ),
    }


@router.post("/auth-server/test")
def test_auth_server(req: AuthServerClientRequest, request: Request):
    """저장 전 URL/키 검증."""
    _require_master(request)
    return auth_server_client.test_connection(req.url, req.api_key)


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, request: Request):
    """현재 비밀번호 확인 후 새 비밀번호로 변경."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "인증이 필요합니다.")
    # 현재 비밀번호 재검증
    db_user = auth_service.authenticate_user(user["sub"], req.current_password)
    if db_user is None:
        raise HTTPException(400, "현재 비밀번호가 올바르지 않습니다.")
    auth_service.update_user(db_user["id"], password=req.new_password)
    return {"ok": True, "message": "비밀번호가 변경되었습니다."}
