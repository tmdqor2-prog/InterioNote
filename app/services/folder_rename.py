"""
v2.5.1 H1 — AI 분석 결과 (site_info) 를 토대로 고객 폴더명 수정 제안.

흐름:
1. analysis 의 site_info 필드들을 읽음
2. 더 자세한 descriptor 를 합성 (예: '자양동 우성아파트_32평/108m2')
3. 사용자에게 제안 → 수락 시 rename
4. rename: 폴더 + DB clients.folder_name/folder_path + meetings.meeting_folder 모두 갱신
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from app.db import db_cursor
from app.services import settings_service

log = logging.getLogger("folder_rename")

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _clean(s: str) -> str:
    return _INVALID_CHARS.sub("", (s or "").strip()).strip()


def suggest_descriptor_from_site_info(site_info: Dict[str, Any]) -> Optional[str]:
    """site_info dict → 새 descriptor 문자열 (괄호 안에 들어갈 내용).
    빈 정보가 많으면 None 반환.
    """
    if not isinstance(site_info, dict):
        return None
    address = _clean(str(site_info.get("address") or ""))
    complex_name = _clean(str(site_info.get("complex_name") or ""))
    building_unit = _clean(str(site_info.get("building_unit") or ""))
    size_pyeong = _clean(str(site_info.get("size_pyeong") or ""))
    size_m2 = _clean(str(site_info.get("size_m2") or ""))
    expansion = _clean(str(site_info.get("expansion") or ""))

    # 핵심: 단지명·평형 둘 다 없으면 의미 있는 제안 못 함
    if not (complex_name or size_pyeong or size_m2):
        return None

    # 형식: "{address} {complex}_{pyeong}/{m2}"  (각 부분이 있을 때만)
    parts = []
    head = " ".join([p for p in [address, complex_name] if p]).strip()
    if head:
        parts.append(head)

    size_bits = []
    if size_pyeong:
        size_bits.append(size_pyeong)
    if size_m2:
        size_bits.append(size_m2)
    if size_bits:
        if parts:
            parts[0] = parts[0] + "_" + "/".join(size_bits)
        else:
            parts.append("_".join(size_bits))

    if building_unit:
        parts.append(building_unit)

    if expansion:
        parts.append(expansion)

    desc = ", ".join(parts).strip(" ,_")
    return desc or None


def rename_client_folder(client_id: int, new_descriptor: str) -> Dict[str, Any]:
    """
    client_id 의 폴더 이름을 '{name} 고객님({new_descriptor})' 형태로 변경.
    실제 디스크 폴더 rename + DB clients.folder_name/folder_path + meetings.meeting_folder 갱신.
    파일 이동 실패 시 원자적 롤백 (DB 갱신 안 함).
    """
    new_descriptor = _clean(new_descriptor)
    if not new_descriptor:
        raise ValueError("새 descriptor 가 비어있습니다.")

    with db_cursor() as cur:
        row = cur.execute(
            "SELECT id, name, descriptor, folder_name, folder_path FROM clients WHERE id = ?",
            (client_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"client {client_id} not found")

    name = row["name"]
    old_folder_name = row["folder_name"]
    old_folder_path = Path(row["folder_path"])
    new_folder_name = f"{name} 고객님({new_descriptor})"

    if new_folder_name == old_folder_name:
        return {"ok": True, "no_change": True, "folder_name": old_folder_name}

    client_root = settings_service.get_client_root()
    new_folder_path = client_root / new_folder_name

    if new_folder_path.exists():
        raise ValueError(f"같은 이름의 폴더가 이미 존재합니다: {new_folder_name}")

    # 1) 디스크 rename (가장 위험한 작업 — 먼저 시도)
    try:
        shutil.move(str(old_folder_path), str(new_folder_path))
    except Exception as e:
        raise RuntimeError(f"폴더 rename 실패 (디스크): {type(e).__name__}: {e}")

    # 2) DB clients 갱신
    try:
        with db_cursor() as cur:
            cur.execute(
                "UPDATE clients SET descriptor = ?, folder_name = ?, folder_path = ? WHERE id = ?",
                (new_descriptor, new_folder_name, str(new_folder_path), client_id),
            )
            # 3) meetings.meeting_folder 도 옛 경로 prefix → 새 경로 prefix 로 치환
            old_prefix = str(old_folder_path)
            new_prefix = str(new_folder_path)
            ms = cur.execute(
                "SELECT id, meeting_folder, audio_file FROM meetings "
                "WHERE client_id = ? AND meeting_folder LIKE ?",
                (client_id, old_prefix + "%"),
            ).fetchall()
            for m in ms:
                mid = m["id"]
                old_mf = m["meeting_folder"] or ""
                old_af = m["audio_file"] or ""
                new_mf = (old_prefix and old_mf.replace(old_prefix, new_prefix)) or old_mf
                new_af = (old_prefix and old_af.replace(old_prefix, new_prefix)) or old_af
                cur.execute(
                    "UPDATE meetings SET meeting_folder = ?, audio_file = ? WHERE id = ?",
                    (new_mf, new_af, mid),
                )
    except Exception as e:
        # DB 실패 시 디스크 롤백 시도
        try:
            shutil.move(str(new_folder_path), str(old_folder_path))
        except Exception:
            pass
        raise RuntimeError(f"DB 갱신 실패 (폴더 원복 시도): {type(e).__name__}: {e}")

    log.info(f"client {client_id} renamed: {old_folder_name} -> {new_folder_name}")
    return {
        "ok": True,
        "old_folder_name": old_folder_name,
        "new_folder_name": new_folder_name,
        "new_folder_path": str(new_folder_path),
        "meetings_updated": len(ms),
    }
