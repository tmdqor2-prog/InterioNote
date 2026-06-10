"""
v3.5.4 — DB 안의 절대경로를 현재 client_root 기준으로 자동 갱신.

배경:
- clients.folder_path, meetings.meeting_folder, meetings.audio_file 모두
  녹음 시점의 절대경로로 저장됨.
- 사용자가 PC 를 옮기거나 외장 SSD 로 복사하면 경로가 깨짐.
- 이 모듈은 "07_고객정보" 토큰을 anchor 로 prefix 만 갈아끼움.

동작:
- preview() 로 미리보기 (변경 예정 카운트 + 샘플)
- migrate() 로 실제 적용 (변경된 파일이 실제 존재하는 것만)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db import db_cursor
from app.services import settings_service

ANCHOR = "07_고객정보"


def _remap(old: Optional[str], new_root: str) -> Optional[str]:
    """경로의 prefix 를 client_root 로 갈아끼움. anchor 못 찾으면 None."""
    if not old:
        return None
    idx = old.find(ANCHOR)
    if idx == -1:
        return None
    after = old[idx + len(ANCHOR):].lstrip("\\").lstrip("/")
    return os.path.join(new_root, after) if after else new_root


def preview() -> Dict[str, Any]:
    """변경 미리보기 — 실제 DB 변경 없이 어떤 행이 바뀔지·실제 폴더 있는지 확인.

    반환: {
        "client_root": str,
        "clients": {"total": N, "to_change": M, "missing_target": K, "samples": [...]},
        "meetings": {...},
    }
    """
    new_root = settings_service.get_client_root()
    new_root_str = str(new_root) if new_root else ""

    with db_cursor() as cur:
        client_rows = cur.execute(
            "SELECT id, name, folder_path FROM clients"
        ).fetchall()
        meeting_rows = cur.execute(
            "SELECT id, meeting_type, started_at, meeting_folder, audio_file "
            "FROM meetings WHERE meeting_folder IS NOT NULL"
        ).fetchall()

    c_to_change = 0
    c_missing = 0
    c_samples: List[Dict[str, Any]] = []
    for r in client_rows:
        new_p = _remap(r["folder_path"], new_root_str)
        if new_p is None or new_p == r["folder_path"]:
            continue
        if os.path.exists(new_p):
            c_to_change += 1
            if len(c_samples) < 5:
                c_samples.append({
                    "name": r["name"],
                    "old": r["folder_path"],
                    "new": new_p,
                })
        else:
            c_missing += 1

    m_to_change = 0
    m_missing = 0
    m_samples: List[Dict[str, Any]] = []
    for r in meeting_rows:
        new_folder = _remap(r["meeting_folder"], new_root_str)
        if new_folder is None or new_folder == r["meeting_folder"]:
            continue
        if os.path.exists(new_folder):
            m_to_change += 1
            if len(m_samples) < 5:
                m_samples.append({
                    "id": r["id"],
                    "type": r["meeting_type"],
                    "date": (r["started_at"] or "")[:10],
                    "old": r["meeting_folder"],
                    "new": new_folder,
                })
        else:
            m_missing += 1

    return {
        "client_root": new_root_str,
        "clients": {
            "total": len(client_rows),
            "to_change": c_to_change,
            "missing_target": c_missing,
            "samples": c_samples,
        },
        "meetings": {
            "total": len(meeting_rows),
            "to_change": m_to_change,
            "missing_target": m_missing,
            "samples": m_samples,
        },
    }


def migrate() -> Dict[str, Any]:
    """실제 마이그레이션 적용 — 새 경로에 폴더/파일이 있는 행만 변경."""
    new_root = settings_service.get_client_root()
    new_root_str = str(new_root) if new_root else ""
    if not new_root_str:
        raise ValueError("client_root 가 설정되지 않았습니다.")

    changed_clients = 0
    changed_meetings = 0
    skipped: List[str] = []

    with db_cursor() as cur:
        # clients
        for r in cur.execute("SELECT id, name, folder_path FROM clients").fetchall():
            new_p = _remap(r["folder_path"], new_root_str)
            if new_p is None or new_p == r["folder_path"]:
                continue
            if not os.path.exists(new_p):
                skipped.append(f"client #{r['id']} ({r['name']}): 새 경로 없음")
                continue
            cur.execute(
                "UPDATE clients SET folder_path = ? WHERE id = ?",
                (new_p, r["id"]),
            )
            changed_clients += 1

        # meetings
        for r in cur.execute(
            "SELECT id, meeting_type, started_at, meeting_folder, audio_file "
            "FROM meetings WHERE meeting_folder IS NOT NULL"
        ).fetchall():
            new_folder = _remap(r["meeting_folder"], new_root_str)
            if new_folder is None or new_folder == r["meeting_folder"]:
                continue
            if not os.path.exists(new_folder):
                skipped.append(f"meeting #{r['id']}: 새 경로 없음")
                continue
            new_audio = _remap(r["audio_file"], new_root_str) if r["audio_file"] else None
            if new_audio and not os.path.exists(new_audio):
                # audio 새 경로 없으면 기존 유지
                new_audio = r["audio_file"]
            cur.execute(
                "UPDATE meetings SET meeting_folder = ?, audio_file = ? WHERE id = ?",
                (new_folder, new_audio, r["id"]),
            )
            changed_meetings += 1

    return {
        "ok": True,
        "client_root": new_root_str,
        "changed_clients": changed_clients,
        "changed_meetings": changed_meetings,
        "skipped": skipped[:50],
        "skipped_count": len(skipped),
    }
