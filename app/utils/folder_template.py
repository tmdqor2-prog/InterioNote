"""
고객 폴더 템플릿 보장.
기존 고객을 선택하면 누락된 서브폴더를 자동으로 만든다.
신규 고객 생성 시에도 같은 함수를 호출.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from app import config
from app.services import settings_service


def ensure_client_template(client_path: Path) -> List[str]:
    """
    고객 폴더 내부에 사용자 설정한 서브폴더가 모두 존재하도록 보장.
    실제로 새로 만든 폴더 이름들만 리스트로 반환.
    Phase 6A: 템플릿은 settings_service.get_folder_template() 에서 가져옴.
    """
    if not client_path.exists():
        raise FileNotFoundError(f"고객 폴더를 찾을 수 없습니다: {client_path}")
    if not client_path.is_dir():
        raise NotADirectoryError(f"폴더가 아닙니다: {client_path}")

    template = settings_service.get_folder_template()
    created: List[str] = []
    for sub in template:
        sub_path = client_path / sub
        if not sub_path.exists():
            sub_path.mkdir(parents=True, exist_ok=True)
            created.append(sub)
    return created


def check_template_status(client_path: Path) -> Dict[str, List[str]]:
    """
    각 템플릿 서브폴더의 존재 여부 확인.
    {"present": [...], "missing": [...]}
    """
    template = settings_service.get_folder_template()
    if not client_path.exists():
        return {"present": [], "missing": list(template)}

    present: List[str] = []
    missing: List[str] = []
    for sub in template:
        (present if (client_path / sub).exists() else missing).append(sub)
    return {"present": present, "missing": missing}
