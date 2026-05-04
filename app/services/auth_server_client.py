"""
v3.5.3 — Auth Server 클라이언트 (노트북 측에서 사용).

데스크톱(Auth Server) 의 API 를 호출하는 헬퍼.
- 로그인 시 데스크톱 호출 후 사용자 정보 로컬 DB 에 캐시
- 회원가입·승인·삭제 등도 데스크톱 호출
- 데스크톱 응답 실패 시 호출자가 폴백 결정 (로컬 DB 사용 등)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.services import auth_service, settings_service

log = logging.getLogger("auth_server_client")


class AuthServerError(Exception):
    """Auth Server 호출 실패 (연결 안 됨, API 키 틀림 등)."""


def _base_url() -> Optional[str]:
    url = (settings_service.get_auth_server_url() or "").rstrip("/")
    return url or None


def _headers() -> dict[str, str]:
    return {
        "X-Auth-Server-Key": settings_service.get_auth_server_client_api_key(),
        "Content-Type": "application/json",
    }


def is_configured() -> bool:
    return settings_service.is_auth_server_client()


def test_connection(url: str, api_key: str) -> dict:
    """저장 전 연결 테스트. 반환: {ok, error?, server_version?, latency_ms?}"""
    import time
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        return {"ok": False, "error": "URL 이 비어 있습니다."}
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        return {"ok": False, "error": "URL 은 http:// 또는 https:// 로 시작해야 합니다."}
    try:
        t0 = time.monotonic()
        r = httpx.get(
            f"{cleaned}/api/auth-server/info",
            headers={"X-Auth-Server-Key": api_key},
            timeout=4.0,
        )
        latency = int((time.monotonic() - t0) * 1000)
        if r.status_code == 401:
            return {"ok": False, "error": "API 키가 올바르지 않습니다. 데스크톱에서 다시 복사해 주세요."}
        if r.status_code == 503:
            return {"ok": False, "error": "데스크톱이 Auth Server 모드가 꺼져 있습니다."}
        r.raise_for_status()
        data = r.json()
        return {"ok": True, "latency_ms": latency, "server_version": data.get("server_version")}
    except httpx.TimeoutException:
        return {"ok": False, "error": "연결 시간 초과 (4초). 데스크톱이 켜져 있는지 / 같은 Tailscale 인지 확인하세요."}
    except httpx.ConnectError as e:
        return {"ok": False, "error": f"연결 실패 — {e}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def remote_login(username: str, password: str) -> Optional[dict]:
    """
    Auth Server 에 로그인 요청.
    성공 시: 사용자 1건 캐시 + JWT 시크릿 동기화 후 user dict 반환.
    실패 시: AuthServerError 또는 None (자격 증명 오류).
    """
    base = _base_url()
    if not base:
        return None
    try:
        r = httpx.post(
            f"{base}/api/auth-server/login",
            json={"username": username, "password": password},
            headers=_headers(),
            timeout=6.0,
        )
        if r.status_code == 401:
            return None  # 자격 증명 오류 → 호출자가 처리
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            return None
        user_data = data["user"]
        # 1) JWT 시크릿 동기화 (이래야 Auth Server 가 발급한 토큰을 클라이언트도 검증 가능)
        sec = data.get("jwt_secret")
        if sec:
            auth_service.replace_jwt_secret(sec)
        # 2) 사용자 정보 로컬 캐시
        auth_service.upsert_synced_user(user_data)
        return user_data
    except httpx.HTTPError as e:
        raise AuthServerError(f"Auth Server 호출 실패: {type(e).__name__}: {e}")


def remote_register(username: str, display_name: str, password: str) -> dict:
    """Auth Server 로 회원가입 신청 전달."""
    base = _base_url()
    if not base:
        raise AuthServerError("Auth Server URL 이 설정되지 않았습니다.")
    try:
        r = httpx.post(
            f"{base}/api/auth-server/register",
            json={"username": username, "display_name": display_name, "password": password},
            headers=_headers(),
            timeout=10.0,
        )
        if r.status_code == 409:
            raise ValueError(r.json().get("detail") or "이미 사용 중인 아이디")
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise AuthServerError(f"가입 신청 실패: {type(e).__name__}: {e}")


def remote_list_users() -> list[dict]:
    """마스터의 사용자 관리 화면용 — 데스크톱의 모든 사용자 목록."""
    base = _base_url()
    if not base:
        raise AuthServerError("Auth Server URL 이 설정되지 않았습니다.")
    try:
        r = httpx.get(f"{base}/api/auth-server/users", headers=_headers(), timeout=6.0)
        r.raise_for_status()
        return r.json().get("users", [])
    except httpx.HTTPError as e:
        raise AuthServerError(f"사용자 목록 조회 실패: {type(e).__name__}: {e}")


def remote_list_pending() -> list[dict]:
    base = _base_url()
    if not base:
        raise AuthServerError("Auth Server URL 이 설정되지 않았습니다.")
    try:
        r = httpx.get(f"{base}/api/auth-server/pending", headers=_headers(), timeout=6.0)
        r.raise_for_status()
        return r.json().get("users", [])
    except httpx.HTTPError as e:
        raise AuthServerError(f"대기자 조회 실패: {type(e).__name__}: {e}")


def remote_approve(user_id: int) -> dict:
    base = _base_url()
    if not base:
        raise AuthServerError("Auth Server URL 이 설정되지 않았습니다.")
    try:
        r = httpx.post(
            f"{base}/api/auth-server/users/{user_id}/approve",
            headers=_headers(), timeout=6.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise AuthServerError(f"승인 실패: {type(e).__name__}: {e}")


def remote_reject(user_id: int) -> dict:
    base = _base_url()
    if not base:
        raise AuthServerError("Auth Server URL 이 설정되지 않았습니다.")
    try:
        r = httpx.delete(
            f"{base}/api/auth-server/users/{user_id}/reject",
            headers=_headers(), timeout=6.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise AuthServerError(f"거절 실패: {type(e).__name__}: {e}")


def remote_update_user(user_id: int, **kwargs) -> dict:
    base = _base_url()
    if not base:
        raise AuthServerError("Auth Server URL 이 설정되지 않았습니다.")
    body = {k: v for k, v in kwargs.items() if v is not None}
    try:
        r = httpx.patch(
            f"{base}/api/auth-server/users/{user_id}",
            json=body, headers=_headers(), timeout=6.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise AuthServerError(f"수정 실패: {type(e).__name__}: {e}")


def remote_delete_user(user_id: int) -> dict:
    base = _base_url()
    if not base:
        raise AuthServerError("Auth Server URL 이 설정되지 않았습니다.")
    try:
        r = httpx.delete(
            f"{base}/api/auth-server/users/{user_id}",
            headers=_headers(), timeout=6.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise AuthServerError(f"삭제 실패: {type(e).__name__}: {e}")
