"""
사용자 설정 관리 (Phase 5A + 6A).

settings 테이블(key/value)에 저장. 기본값은 config.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import config
from app.db import db_cursor


# Windows 파일시스템 금지 문자 제거 (폴더명 정제용)
_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_folder_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    return _INVALID_FOLDER_CHARS.sub("", name).strip()


# ========================================
# Whisper 모델 사이즈
# ========================================
WHISPER_MODEL_CHOICES = ["tiny", "base", "small", "medium", "large-v3"]


def get_whisper_model_size() -> str:
    val = _get("whisper.model_size")
    if val and val in WHISPER_MODEL_CHOICES:
        return val
    return config.WHISPER_MODEL_SIZE


def set_whisper_model_size(size: str) -> None:
    if size not in WHISPER_MODEL_CHOICES:
        raise ValueError(f"허용되지 않는 모델: {size}. 가능: {WHISPER_MODEL_CHOICES}")
    _set("whisper.model_size", size)


def get_whisper_beam_size() -> int:
    val = _get("whisper.beam_size")
    if val:
        try:
            n = int(val)
            if 1 <= n <= 8:
                return n
        except ValueError:
            pass
    return config.WHISPER_BEAM_SIZE


def set_whisper_beam_size(n: int) -> None:
    if not (1 <= int(n) <= 8):
        raise ValueError("beam_size 는 1~8 사이여야 합니다.")
    _set("whisper.beam_size", str(int(n)))


# ========================================
# 인테리어 키워드 사전 (initial_prompt)
# ========================================
DEFAULT_INTERIOR_VOCAB = (
    "인테리어 상담 녹음.\n"
    "공간: 평수, 방, 거실, 주방, 욕실, 안방, 작은방, 드레스룸, 파우더룸, 베란다, 발코니, 확장.\n"
    "구조: 철거, 목공, 천장고, 몰딩, 걸레받이, 아트월, 포인트벽, 가벽.\n"
    "창호: 샷시, 이중창, 중문, 슬라이딩도어, 폴딩도어, 방충망.\n"
    "마감: 도배, 벽지, 페인트, 도장, 친환경, E0, E1.\n"
    "바닥: 강마루, 강화마루, 원목마루, 장판, 폴리싱타일, 포세린타일.\n"
    "주방: 싱크대, 상부장, 하부장, 아일랜드, 쿡탑, 인덕션, 후드, 빌트인.\n"
    "욕실: 젠다이, 세면대, 수전, 양변기, 수납장, 거울장.\n"
    "수납: 붙박이장, 시스템행거, 팬트리.\n"
    "설비: 배관, 배선, 콘센트, 스위치, 누수, 결로, 곰팡이, 단열.\n"
    "조명: 다운라이트, 간접등, 매입등, 직부등, 펜던트, 레일등, 디밍.\n"
    "자재: 원목, 집성목, MDF, 필름, 하이그로시, 무광, 유광.\n"
    "견적: 평단가, 턴키, 반셀프, 부분시공, 견적서, 계약금, 중도금, 잔금.\n"
    "공정: 공정표, 실측, 착공, 준공, AS, 하자.\n"
    "스타일: 모던, 북유럽, 내추럴, 클래식, 인더스트리얼, 미니멀, 빈티지."
)


def get_interior_vocab() -> str:
    val = _get("whisper.interior_vocab")
    return val if val is not None else DEFAULT_INTERIOR_VOCAB


def set_interior_vocab(text: str) -> None:
    text = (text or "").strip()
    _set("whisper.interior_vocab", text)


def reset_interior_vocab() -> None:
    _set("whisper.interior_vocab", DEFAULT_INTERIOR_VOCAB)


def get_interior_vocab_for_prompt() -> str:
    """
    Whisper initial_prompt 용. 줄바꿈을 공백으로 합쳐 한 줄짜리 hint 로.
    """
    text = get_interior_vocab()
    if not text:
        return ""
    flat = " ".join(part.strip() for part in text.splitlines() if part.strip())
    return flat


# ========================================
# 노이즈 억제 (Phase 5B 에서 활성화)
# ========================================
def get_noise_suppression_enabled() -> bool:
    return _get_bool("noise.suppression_enabled", False)


def set_noise_suppression_enabled(enabled: bool) -> None:
    _set_bool("noise.suppression_enabled", enabled)


# ========================================
# 저장 위치 (Phase 6A)
# ========================================
def get_client_root() -> Path:
    val = _get("paths.client_root")
    if val:
        return Path(val)
    return config.CLIENT_ROOT


def set_client_root(path_str: str) -> Path:
    """
    고객 폴더 루트 변경.
    - 빈 문자열 거부
    - resolve() 로 절대 경로화
    - 폴더 존재 검증은 호출자(API) 에서 별도 안내 (없으면 만들도록 옵션)
    """
    if not isinstance(path_str, str):
        raise ValueError("경로는 문자열이어야 합니다.")
    s = path_str.strip().strip('"').strip("'")
    if not s:
        raise ValueError("경로가 비어 있습니다.")
    p = Path(s).expanduser().resolve()
    _set("paths.client_root", str(p))
    return p


# ========================================
# 폴더 템플릿 (Phase 6A)
# 신규 고객 생성 시 자동으로 만들어지는 서브폴더 목록.
# '상담기록' 은 시스템 필수 — 자동 유지.
# ========================================
REQUIRED_FOLDER = "상담기록"


def get_folder_template() -> List[str]:
    val = _get("paths.folder_template")
    if val:
        try:
            data = json.loads(val)
            if isinstance(data, list):
                cleaned = [s for s in (_sanitize_folder_name(x) for x in data) if s]
                if cleaned:
                    if REQUIRED_FOLDER not in cleaned:
                        cleaned.append(REQUIRED_FOLDER)
                    return cleaned
        except json.JSONDecodeError:
            pass
    # 기본값
    return list(config.FOLDER_TEMPLATE)


def set_folder_template(folders: List[str]) -> List[str]:
    """
    UI 에서 받은 폴더 이름 리스트를 정제·중복 제거하고 저장.
    '상담기록' 은 항상 포함 (제거 불가).
    """
    if not isinstance(folders, list):
        raise ValueError("folder_template 은 리스트여야 합니다.")
    cleaned: List[str] = []
    seen = set()
    for f in folders:
        s = _sanitize_folder_name(f) if isinstance(f, str) else ""
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    if not cleaned:
        raise ValueError("최소 한 개의 폴더 이름이 필요합니다.")
    if REQUIRED_FOLDER not in seen:
        cleaned.append(REQUIRED_FOLDER)
    _set("paths.folder_template", json.dumps(cleaned, ensure_ascii=False))
    return cleaned


# ========================================
# VAD 임계값 (Phase 5B에서 미세조정 옵션)
# ========================================
def get_vad_threshold() -> float:
    val = _get("vad.threshold")
    if val:
        try:
            f = float(val)
            if 0.1 <= f <= 0.95:
                return f
        except ValueError:
            pass
    return 0.5


def set_vad_threshold(value: float) -> None:
    if not (0.1 <= float(value) <= 0.95):
        raise ValueError("VAD threshold 는 0.1 ~ 0.95 사이여야 합니다.")
    _set("vad.threshold", f"{float(value):.2f}")


# ========================================
# 한꺼번에 조회 (UI 용)
# ========================================
def get_all_settings() -> Dict[str, Any]:
    client_root = get_client_root()
    return {
        "whisper": {
            "model_size": get_whisper_model_size(),
            "beam_size": get_whisper_beam_size(),
            "model_choices": WHISPER_MODEL_CHOICES,
            "interior_vocab": get_interior_vocab(),
            "default_interior_vocab": DEFAULT_INTERIOR_VOCAB,
        },
        "noise": {
            "suppression_enabled": get_noise_suppression_enabled(),
        },
        "vad": {
            "threshold": get_vad_threshold(),
        },
        "paths": {
            "client_root": str(client_root),
            "client_root_exists": client_root.exists(),
            "folder_template": get_folder_template(),
            "default_folder_template": list(config.FOLDER_TEMPLATE),
            "required_folder": REQUIRED_FOLDER,
        },
    }


# ========================================
# 내부 헬퍼
# ========================================
def _get(key: str) -> Optional[str]:
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def _set(key: str, value: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def _get_bool(key: str, default: bool) -> bool:
    val = _get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _set_bool(key: str, value: bool) -> None:
    _set(key, "1" if value else "0")
