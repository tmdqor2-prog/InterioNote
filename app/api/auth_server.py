"""
v3.5.3 — Auth Server 엔드포인트 (중앙 계정 관리).

이 PC 가 데스크톱(Auth Server) 일 때 다른 PC(노트북) 에서 호출하는 API.
모든 엔드포인트는 X-Auth-Server-Key 헤더로 인증 (JWT 와 별개).

개념:
    - 데스크톱 = users 테이블의 진실의 원천 (master 본인 계정 + 일반 사용자)
    - 노트북 = 클라이언트. 로그인 시 데스크톱에서 동기화해서 로컬 DB 캐시
    - 회원가입은 노트북에서도 가능. 단, 실제 데이터는 데스크톱 DB 에 저장됨
    - 마스터의 사용자 관리 (승인/거절/삭제) 는 어느 PC 에서나 가능 (모두 데스크톱으로 위임)

엔드포인트:
    GET  /api/auth-server/info        : 서버 동작 확인 (헬스체크)
    POST /api/auth-server/login       : 노트북에서 사용자 로그인 시 호출 (사용자 1건 + JWT 시크릿 동기화)
    POST /api/auth-server/register    : 노트북에서 회원가입 신청 시 호출
    GET  /api/auth-server/users       : 모든 사용자 목록 (마스터 관리용)
    GET  /api/auth-server/pending     : 승인 대기 사용자 목록
    POST /api/auth-server/users/{id}/approve : 가입 승인
    DELETE /api/auth-server/users/{id}/reject : 가입 거절
    PATCH  /api/auth-server/users/{id}        : 사용자 수정 (비밀번호·이름·역할)
    DELETE /api/auth-server/users/{id}        : 사용자 삭제
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.db import db_cursor, get_setting
from app.services import auth_service, settings_service

router = APIRouter(prefix="/api/auth-server", tags=["auth-server"])


# ─── API 키 검증 (모든 엔드포인트 공통) ───────────────────────────────────────

def _require_api_key(x_auth_server_key: Optional[str]) -> None:
    """이 PC 가 Auth Server 모드 ON + 보낸 키가 일치해야 통과."""
    if not settings_service.get_auth_server_enabled():
        raise HTTPException(503, "이 PC 는 Auth Server 모드가 꺼져 있습니다.")
    expected = settings_service.get_auth_server_api_key()
    if not x_auth_server_key or x_auth_server_key != expected:
        raise HTTPException(401, "Auth Server API 키가 올바르지 않습니다.")


# ─── 엔드포인트 ───────────────────────────────────────────────────────────────

@router.get("/info")
def info(x_auth_server_key: Optional[str] = Header(None)):
    """헬스체크 — API 키 + 서버 동작 확인. JWT 시크릿도 함께 반환 (클라이언트 캐시용)."""
    _require_api_key(x_auth_server_key)
    return {
        "ok": True,
        "server_version": "3.5.3",
        # 클라이언트가 Auth Server 가 발급한 JWT 도 검증할 수 있도록
        # 시크릿을 동기화 받음 (Tailscale + API 키로 보호되는 채널)
        "jwt_secret": get_setting("auth.jwt_secret") or "",
    }


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


@router.post("/login")
def server_login(req: LoginRequest, x_auth_server_key: Optional[str] = Header(None)):
    """클라이언트(노트북) 가 사용자 로그인을 위임할 때 호출.
    성공 시: user_data (password_hash 포함) + JWT 토큰 + JWT 시크릿 반환.
    클라이언트는 user_data 를 자기 DB 에 캐시해서 다음부터 오프라인 로그인 가능하게 만듦.
    """
    _require_api_key(x_auth_server_key)
    user = auth_service.authenticate_user(req.username, req.password)
    if user is None:
        status = auth_service.get_user_status(req.username)
        if status == "pending":
            raise HTTPException(401, "가입 승인 대기 중입니다.")
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    token = auth_service.create_token(user)
    return {
        "ok": True,
        "token": token,
        "jwt_secret": get_setting("auth.jwt_secret") or "",
        "user": {
            "username": user["username"],
            "display_name": user["display_name"],
            "password_hash": user["password_hash"],
            "role": user["role"],
            "is_active": user["is_active"],
            "status": user.get("status") or "active",
        },
    }


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=30, pattern=r"^[a-zA-Z0-9_]+$")
    display_name: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=4, max_length=100)


@router.post("/register", status_code=201)
def server_register(req: RegisterRequest, x_auth_server_key: Optional[str] = Header(None)):
    """클라이언트가 회원가입 신청을 위임."""
    _require_api_key(x_auth_server_key)
    try:
        user = auth_service.register_user(req.username, req.display_name, req.password)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "username": user["username"]}


@router.get("/users")
def server_list_users(x_auth_server_key: Optional[str] = Header(None)):
    _require_api_key(x_auth_server_key)
    return {"users": auth_service.get_all_users()}


@router.get("/pending")
def server_list_pending(x_auth_server_key: Optional[str] = Header(None)):
    _require_api_key(x_auth_server_key)
    return {"users": auth_service.get_pending_users()}


@router.post("/users/{user_id}/approve")
def server_approve(user_id: int, x_auth_server_key: Optional[str] = Header(None)):
    _require_api_key(x_auth_server_key)
    user = auth_service.approve_user(user_id)
    if user is None:
        raise HTTPException(404, "대기 중인 사용자를 찾을 수 없습니다.")
    return {"ok": True, "user": user}


@router.delete("/users/{user_id}/reject")
def server_reject(user_id: int, x_auth_server_key: Optional[str] = Header(None)):
    _require_api_key(x_auth_server_key)
    auth_service.reject_user(user_id)
    return {"ok": True}


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


@router.patch("/users/{user_id}")
def server_update_user(user_id: int, req: UserUpdateRequest, x_auth_server_key: Optional[str] = Header(None)):
    _require_api_key(x_auth_server_key)
    user = auth_service.update_user(
        user_id,
        display_name=req.display_name,
        password=req.password,
        role=req.role,
        is_active=req.is_active,
    )
    if user is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    return {"ok": True, "user": user}


@router.delete("/users/{user_id}")
def server_delete_user(user_id: int, x_auth_server_key: Optional[str] = Header(None)):
    _require_api_key(x_auth_server_key)
    auth_service.delete_user(user_id)
    return {"ok": True}
