"""
v3.0.0 Phase 2 — 사용자 관리 API (마스터 전용).
v3.3.0 Phase 5 — 가입 승인/거절 추가.

GET    /api/users             : 활성 사용자 목록
GET    /api/users/pending     : 승인 대기 사용자 목록
POST   /api/users             : 신규 계정 생성 (마스터가 직접 생성 → 즉시 활성)
PATCH  /api/users/{user_id}   : 계정 정보 수정 (이름/비번/역할/활성화)
DELETE /api/users/{user_id}   : 계정 삭제 (마스터 계정 삭제 불가)
POST   /api/users/{user_id}/approve : 가입 승인 (pending → active)
POST   /api/users/{user_id}/reject  : 가입 거절 (pending 삭제)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services import auth_server_client, auth_service

router = APIRouter(prefix="/api/users", tags=["users"])


# ─── 헬퍼 ────────────────────────────────────────────────────────────────────

def _require_master(request: Request) -> dict:
    """마스터 역할이 아니면 403. 마스터 payload 반환."""
    user = getattr(request.state, "user", None)
    if user is None or user.get("role") != "master":
        raise HTTPException(403, "마스터 권한이 필요합니다.")
    return user


# ─── 요청 모델 ───────────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=30, pattern=r"^[a-zA-Z0-9_]+$")
    display_name: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=4, max_length=100)
    role: str = Field("user", pattern=r"^(master|user)$")


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=50)
    password: Optional[str] = Field(None, min_length=4, max_length=100)
    role: Optional[str] = Field(None, pattern=r"^(master|user)$")
    is_active: Optional[bool] = None


# ─── 엔드포인트 ───────────────────────────────────────────────────────────────

def _proxy_to_auth_server() -> bool:
    """이 PC 가 Auth Server 의 클라이언트면 True (사용자 관리 호출 위임)."""
    return auth_server_client.is_configured()


@router.get("")
def list_users(request: Request):
    _require_master(request)
    # v3.5.3: 클라이언트면 데스크톱 (Auth Server) 의 목록 조회
    if _proxy_to_auth_server():
        try:
            return auth_server_client.remote_list_users()
        except auth_server_client.AuthServerError as e:
            raise HTTPException(503, f"Auth Server 호출 실패 — {e}")
    return auth_service.get_all_users()


@router.get("/pending")
def list_pending_users(request: Request):
    """승인 대기 사용자 목록 (마스터 전용)."""
    _require_master(request)
    if _proxy_to_auth_server():
        try:
            return auth_server_client.remote_list_pending()
        except auth_server_client.AuthServerError as e:
            raise HTTPException(503, f"Auth Server 호출 실패 — {e}")
    return auth_service.get_pending_users()


@router.post("", status_code=201)
def create_user(req: CreateUserRequest, request: Request):
    _require_master(request)
    if _proxy_to_auth_server():
        # 클라이언트는 직접 가입 못 함 — 가입 신청 API 사용 (이미 Auth Server 로 위임됨)
        raise HTTPException(
            400,
            "이 PC 는 Auth Server 의 클라이언트입니다. 데스크톱(Auth Server)에서 직접 계정을 생성하거나, "
            "회원가입 신청 → 승인 흐름을 사용하세요."
        )
    try:
        user = auth_service.create_user(
            req.username, req.display_name, req.password, req.role
        )
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            raise HTTPException(409, f"아이디 '{req.username}'은 이미 사용 중입니다.")
        raise HTTPException(500, f"사용자 생성 실패: {type(e).__name__}: {str(e)[:200]}")
    return user


@router.patch("/{user_id}")
def update_user(user_id: int, req: UpdateUserRequest, request: Request):
    me = _require_master(request)
    if _proxy_to_auth_server():
        try:
            return auth_server_client.remote_update_user(
                user_id,
                display_name=req.display_name,
                password=req.password,
                role=req.role,
                is_active=req.is_active,
            )
        except auth_server_client.AuthServerError as e:
            raise HTTPException(503, f"Auth Server 호출 실패 — {e}")
    target = auth_service.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    if target["username"] == me["sub"]:
        if req.role == "user":
            raise HTTPException(400, "자신의 역할을 일반 사용자로 강등할 수 없습니다.")
        if req.is_active is False:
            raise HTTPException(400, "자신의 계정을 비활성화할 수 없습니다.")
    updated = auth_service.update_user(
        user_id,
        display_name=req.display_name,
        password=req.password,
        role=req.role,
        is_active=req.is_active,
    )
    return updated


@router.delete("/{user_id}")
def delete_user(user_id: int, request: Request):
    me = _require_master(request)
    if _proxy_to_auth_server():
        try:
            return auth_server_client.remote_delete_user(user_id)
        except auth_server_client.AuthServerError as e:
            raise HTTPException(503, f"Auth Server 호출 실패 — {e}")
    target = auth_service.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    if target["username"] == me["sub"]:
        raise HTTPException(400, "자기 자신은 삭제할 수 없습니다.")
    if target["role"] == "master":
        raise HTTPException(400, "마스터 계정은 삭제할 수 없습니다.")
    auth_service.delete_user(user_id)
    return {"ok": True}


@router.post("/{user_id}/approve")
def approve_user(user_id: int, request: Request):
    """가입 신청 승인 — pending → active."""
    _require_master(request)
    if _proxy_to_auth_server():
        try:
            return auth_server_client.remote_approve(user_id)
        except auth_server_client.AuthServerError as e:
            raise HTTPException(503, f"Auth Server 호출 실패 — {e}")
    user = auth_service.approve_user(user_id)
    if user is None:
        raise HTTPException(404, "승인 대기 사용자를 찾을 수 없습니다.")
    return {"ok": True, "user": user}


@router.post("/{user_id}/reject")
def reject_user(user_id: int, request: Request):
    """가입 신청 거절 — pending 사용자 삭제."""
    _require_master(request)
    if _proxy_to_auth_server():
        try:
            return auth_server_client.remote_reject(user_id)
        except auth_server_client.AuthServerError as e:
            raise HTTPException(503, f"Auth Server 호출 실패 — {e}")
    target = auth_service.get_user_by_id(user_id)
    if target is None or target.get("status") != "pending":
        raise HTTPException(404, "승인 대기 사용자를 찾을 수 없습니다.")
    auth_service.reject_user(user_id)
    return {"ok": True}
