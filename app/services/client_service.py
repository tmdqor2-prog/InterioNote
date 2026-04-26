"""
고객 DB 유틸 — 폴더 스캔 결과와 DB의 clients 테이블을 동기화.

운영 시점 상 14명의 기존 고객 폴더는 DB에 등록되지 않은 상태.
사용자가 상담을 시작할 때 해당 폴더의 고객 row를 자동으로 upsert 한다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app import config
from app.db import db_cursor
from app.services import settings_service
from app.utils.folder_scanner import parse_client_name


def _row_to_dict(row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def get_client_by_folder(folder_name: str) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT * FROM clients WHERE folder_name = ?",
            (folder_name,),
        ).fetchone()
        return _row_to_dict(row) if row else None


def upsert_client_by_folder(folder_name: str) -> Dict[str, Any]:
    """
    07_고객정보 아래의 실제 폴더를 clients 테이블에 보장.
    이미 있으면 그대로 반환, 없으면 폴더명에서 이름/괄호 내용을 파싱해 INSERT.
    """
    existing = get_client_by_folder(folder_name)
    if existing is not None:
        return existing

    client_root = settings_service.get_client_root()
    folder_path = (client_root / folder_name).resolve()
    if not folder_path.exists() or not folder_path.is_dir():
        raise FileNotFoundError(f"고객 폴더를 찾을 수 없습니다: {folder_path}")

    # CLIENT_ROOT 바깥 차단
    folder_path.relative_to(client_root.resolve())

    name, descriptor = parse_client_name(folder_name)
    descriptor = descriptor or None
    first_met = datetime.now().date().isoformat()

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO clients (name, descriptor, folder_name, folder_path, first_met_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, descriptor, folder_name, str(folder_path), first_met),
        )
        client_id = cur.lastrowid
        row = cur.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return _row_to_dict(row)


def get_client(client_id: int) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
