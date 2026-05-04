"""
v3.0.0 Phase 2 — JWT + bcrypt 인증 서비스.
v3.3.0 Phase 5 — 자기 등록 + 마스터 승인 플로우 추가.

- JWT secret: settings DB 에 자동 생성 (없으면 최초 1회 생성)
- 마스터 계정: admin / 1234 (앱 최초 실행 시 자동 생성)
- 토큰 만료: 30일
- 역할(role): 'master' (전체 권한) / 'user' (녹음·분석만)
- status: 'active' (정상) | 'pending' (승인 대기)
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
import jwt

from app.db import db_cursor, get_setting, set_setting

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30

MASTER_USERNAME = "admin"
MASTER_DEFAULT_PASSWORD = "1234"
MASTER_DISPLAY_NAME = "한승민"


# ─── 내부 헬퍼 ───────────────────────────────────────────────────────────────

def _get_jwt_secret() -> str:
    """settings DB 에서 JWT secret 를 읽거나, 없으면 새로 생성·저장."""
    secret = get_setting("auth.jwt_secret")
    if not secret:
        secret = secrets.token_hex(32)
        set_setting("auth.jwt_secret", secret)
    return secret


# ─── 비밀번호 ─────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """bcrypt 해시 생성 (bcrypt 직접 사용 — passlib 없음, 버전 호환성 확보)."""
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ─── JWT ─────────────────────────────────────────────────────────────────────

def create_token(user: dict) -> str:
    payload = {
        "sub": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """유효한 JWT 이면 payload dict 반환, 만료·위조 등 실패 시 None."""
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ─── 사용자 인증 ──────────────────────────────────────────────────────────────

def authenticate_user(username: str, password: str) -> Optional[dict]:
    """username + password 검증. 성공·활성 계정이면 user row dict, 실패 시 None.
    pending/비활성 계정은 인증 자체를 거부 (None 반환).
    """
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1 "
            "AND (status = 'active' OR status IS NULL)",
            (username,),
        ).fetchone()
    if row is None:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return dict(row)


def get_user_status(username: str) -> Optional[str]:
    """username 의 status 반환 (존재하지 않으면 None)."""
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT status FROM users WHERE username = ?", (username,)
        ).fetchone()
    return row["status"] if row else None


# ─── 초기 마스터 계정 ─────────────────────────────────────────────────────────

def ensure_master_user() -> None:
    """앱 시작 시 마스터 계정이 하나도 없으면 기본 계정 자동 생성."""
    with db_cursor() as cur:
        existing = cur.execute(
            "SELECT id FROM users WHERE role = 'master'"
        ).fetchone()
        if existing is None:
            cur.execute(
                "INSERT INTO users(username, display_name, password_hash, role) "
                "VALUES(?, ?, ?, ?)",
                (
                    MASTER_USERNAME,
                    MASTER_DISPLAY_NAME,
                    hash_password(MASTER_DEFAULT_PASSWORD),
                    "master",
                ),
            )
            print(
                f"[auth] 마스터 계정 자동 생성: {MASTER_USERNAME} / {MASTER_DEFAULT_PASSWORD}",
                flush=True,
            )


# ─── 사용자 CRUD ──────────────────────────────────────────────────────────────

_USER_COLS = "id, username, display_name, role, is_active, status, created_at"


def get_all_users() -> list[dict]:
    """활성 계정만 반환 (pending 제외). 마스터 사용자 관리 목록용."""
    with db_cursor() as cur:
        rows = cur.execute(
            f"SELECT {_USER_COLS} FROM users "
            "WHERE status = 'active' OR status IS NULL "
            "ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_pending_users() -> list[dict]:
    """승인 대기 중인 사용자 목록."""
    with db_cursor() as cur:
        rows = cur.execute(
            f"SELECT {_USER_COLS} FROM users WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def get_user_by_id(user_id: int) -> Optional[dict]:
    with db_cursor() as cur:
        row = cur.execute(
            f"SELECT {_USER_COLS} FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def create_user(
    username: str,
    display_name: str,
    password: str,
    role: str = "user",
) -> dict:
    """마스터가 직접 계정 생성 — 즉시 active."""
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO users(username, display_name, password_hash, role, status) "
            "VALUES(?, ?, ?, ?, 'active')",
            (username, display_name, hash_password(password), role),
        )
        row = cur.execute(
            f"SELECT {_USER_COLS} FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row)


def register_user(username: str, display_name: str, password: str) -> dict:
    """사용자 자체 회원가입 신청 — status='pending', 로그인 불가 상태로 생성."""
    import sqlite3 as _sqlite3
    with db_cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO users(username, display_name, password_hash, role, is_active, status) "
                "VALUES(?, ?, ?, 'user', 0, 'pending')",
                (username, display_name, hash_password(password)),
            )
        except _sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e).upper():
                raise ValueError(f"아이디 '{username}'은 이미 사용 중입니다.")
            raise
        row = cur.execute(
            f"SELECT {_USER_COLS} FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row)


def approve_user(user_id: int) -> Optional[dict]:
    """pending → active (로그인 가능 상태로 변경)."""
    with db_cursor() as cur:
        cur.execute(
            "UPDATE users SET status = 'active', is_active = 1 "
            "WHERE id = ? AND status = 'pending'",
            (user_id,),
        )
        row = cur.execute(
            f"SELECT {_USER_COLS} FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def reject_user(user_id: int) -> bool:
    """pending 사용자 가입 거절 (삭제)."""
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM users WHERE id = ? AND status = 'pending'", (user_id,)
        )
    return True


def update_user(
    user_id: int,
    *,
    display_name: Optional[str] = None,
    password: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[dict]:
    with db_cursor() as cur:
        if display_name is not None:
            cur.execute(
                "UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id)
            )
        if password is not None:
            cur.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), user_id),
            )
        if role is not None:
            cur.execute(
                "UPDATE users SET role = ? WHERE id = ?", (role, user_id)
            )
        if is_active is not None:
            cur.execute(
                "UPDATE users SET is_active = ? WHERE id = ?",
                (1 if is_active else 0, user_id),
            )
        row = cur.execute(
            f"SELECT {_USER_COLS} FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_user(user_id: int) -> bool:
    """마스터가 아닌 계정만 삭제 가능."""
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM users WHERE id = ? AND role != 'master'", (user_id,)
        )
    return True


# ─── v3.5.2: 사용자별 원격 Ollama URL ────────────────────────────────────────
# 마스터 사용자가 본인의 고사양 데스크톱 Ollama 를 노트북에서 활용하기 위한 설정.
# 다른 사용자(일반)는 빈 값 → 자동으로 본인 PC 의 로컬 Ollama 사용.

def get_user_ollama_url(username: str) -> Optional[str]:
    """username 의 ollama_remote_url 반환 (없으면 None)."""
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT ollama_remote_url FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return None
    url = row["ollama_remote_url"]
    return url.strip() if url and url.strip() else None


def set_user_ollama_url(username: str, url: Optional[str]) -> None:
    """username 의 ollama_remote_url 갱신. None/빈 문자열 → NULL 저장 (= 로컬 사용)."""
    cleaned = (url or "").strip() or None
    with db_cursor() as cur:
        cur.execute(
            "UPDATE users SET ollama_remote_url = ? WHERE username = ?",
            (cleaned, username),
        )


# ─── v3.5.3: Auth Server 동기화 (중앙 계정 관리) ─────────────────────────────
# 원리:
#   - 데스크톱(Auth Server) 의 users 테이블이 진실의 원천
#   - 노트북(클라이언트) 은 Auth Server 에서 사용자 목록 + JWT 시크릿 동기화
#   - 동기화 후 노트북에서도 Auth Server 의 사용자가 그대로 로그인 가능
#   - 새 가입자는 노트북에서 가입해도 Auth Server 로 전송됨

def upsert_synced_user(user_data: dict) -> None:
    """Auth Server 에서 받아온 사용자 1건을 로컬 DB 에 upsert.

    user_data 필드: username, display_name, password_hash, role, is_active, status
    from_auth_server=1 로 표시 (동기화된 캐시임을 구분).
    """
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO users(username, display_name, password_hash, role, "
            "                  is_active, status, from_auth_server) "
            "VALUES(?, ?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(username) DO UPDATE SET "
            "  display_name = excluded.display_name, "
            "  password_hash = excluded.password_hash, "
            "  role = excluded.role, "
            "  is_active = excluded.is_active, "
            "  status = excluded.status, "
            "  from_auth_server = 1",
            (
                user_data["username"],
                user_data.get("display_name") or user_data["username"],
                user_data["password_hash"],
                user_data.get("role", "user"),
                int(user_data.get("is_active", 1)),
                user_data.get("status", "active"),
            ),
        )


def delete_synced_user(username: str) -> None:
    """동기화된 사용자만 삭제 (로컬 직접 가입자는 보호)."""
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM users WHERE username = ? AND from_auth_server = 1",
            (username,),
        )


def replace_jwt_secret(new_secret: str) -> None:
    """Auth Server 에서 받아온 JWT 시크릿으로 교체 (클라이언트 측에서 호출).
    이렇게 해야 Auth Server 가 발급한 JWT 도 클라이언트가 검증 가능.
    """
    if not new_secret or len(new_secret) < 16:
        return
    set_setting("auth.jwt_secret", new_secret)


def export_all_users_for_sync() -> list[dict]:
    """Auth Server 측에서 호출 — 모든 사용자(password_hash 포함) 내보내기.
    클라이언트 PC 가 로컬 캐시를 갱신하는 데 사용함.
    API 키로만 접근 가능 (api/auth-server.py 의 미들웨어 검증).
    """
    with db_cursor() as cur:
        rows = cur.execute(
            "SELECT username, display_name, password_hash, role, is_active, status "
            "FROM users WHERE from_auth_server = 0 OR from_auth_server IS NULL"
        ).fetchall()
    return [dict(r) for r in rows]
