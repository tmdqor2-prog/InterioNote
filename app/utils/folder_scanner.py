"""
07_고객정보 폴더 스캔.
실제 운영 중인 고객 폴더명 규칙:
  "{이름} 고객님({내용})"     ← 일반
  "{회사명}건축" / "{회사명}공사"  ← 기업 고객
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app import config
from app.services import settings_service


def is_client_folder_name(name: str) -> bool:
    """휴리스틱: 고객 폴더로 인정할지."""
    return "고객님" in name or "건축" in name or "공사" in name


def parse_client_name(folder_name: str) -> Tuple[str, str]:
    """
    "김경호 고객님(dmc래미안_26평, 204-1002)" -> ("김경호", "dmc래미안_26평, 204-1002")
    "다미건축(개봉동 주상복합 신축공사)"      -> ("다미건축", "개봉동 주상복합 신축공사")
    "윤은애 고객님(대흥동 태영APT)_43평형"    -> ("윤은애", "대흥동 태영APT)_43평형")
    괄호가 없으면 descriptor는 빈 문자열.
    """
    name = folder_name
    descriptor = ""
    if "(" in name:
        paren_start = name.index("(")
        base = name[:paren_start].strip()
        rest = name[paren_start + 1:]
        if ")" in rest:
            # 마지막 ')' 를 기준으로 descriptor 추출 (중간에 ')' 가 있어도 OK)
            paren_end = rest.rindex(")")
            descriptor = rest[:paren_end].strip()
            trailing = rest[paren_end + 1:].strip()
            if trailing:
                descriptor = f"{descriptor}){trailing}"
        else:
            descriptor = rest.strip()
    else:
        base = name.strip()
    # "김경호 고객님" 에서 "고객님" 접미사 제거
    if base.endswith("고객님"):
        base = base[:-3].rstrip()
    return base, descriptor


def scan_clients() -> List[Dict]:
    """
    CLIENT_ROOT 아래 디렉터리를 훑어 고객 폴더 리스트를 만든다.
    DB와 동기화하지는 않음 (읽기 전용 스캔).
    Phase 6A: settings_service.get_client_root() 를 따라감.
    """
    client_root = settings_service.get_client_root()
    if not client_root.exists():
        return []

    clients: List[Dict] = []
    for entry in sorted(client_root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if not is_client_folder_name(entry.name):
            continue

        name, descriptor = parse_client_name(entry.name)

        # 상담기록 폴더 아래 기존 상담 건수
        records_dir = entry / "상담기록"
        num_meetings = 0
        if records_dir.exists():
            try:
                num_meetings = sum(1 for p in records_dir.iterdir() if p.is_dir())
            except PermissionError:
                num_meetings = 0

        # 마지막 수정 시각 (근거 표시용)
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            mtime = 0

        clients.append(
            {
                "folder_name": entry.name,
                "name": name,
                "descriptor": descriptor,
                "folder_path": str(entry),
                "num_meetings": num_meetings,
                "mtime": mtime,
            }
        )
    # 최근에 건드린 폴더가 위로
    clients.sort(key=lambda c: c["mtime"], reverse=True)
    return clients


def find_client_by_folder(folder_name: str) -> Optional[Dict]:
    for c in scan_clients():
        if c["folder_name"] == folder_name:
            return c
    return None
