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
# Whisper 디바이스 선택 (Phase 8B)
# 'auto' = GPU 가능하면 GPU, 아니면 CPU
# 'cpu'  = 강제 CPU
# 'cuda' = 강제 GPU (실패 시 에러)
# ========================================
WHISPER_DEVICE_CHOICES = ["auto", "cpu", "cuda"]


def get_whisper_device() -> str:
    val = _get("whisper.device")
    if val and val in WHISPER_DEVICE_CHOICES:
        return val
    return "auto"  # 기본값: 자동 감지


def set_whisper_device(device: str) -> None:
    if device not in WHISPER_DEVICE_CHOICES:
        raise ValueError(f"허용되지 않는 디바이스: {device}. 가능: {WHISPER_DEVICE_CHOICES}")
    _set("whisper.device", device)


# ========================================
# v2.5.0: 재전사 모델 마지막 선택 기억 (세션 간 유지)
# ========================================
def get_last_post_model() -> str:
    val = _get("whisper.last_post_model")
    if val and val in WHISPER_MODEL_CHOICES:
        return val
    return "medium"  # 기본값


def set_last_post_model(size: str) -> None:
    if size not in WHISPER_MODEL_CHOICES:
        return  # silent ignore for invalid
    _set("whisper.last_post_model", size)


# ========================================
# 인테리어 키워드 사전 (initial_prompt)
# ========================================
DEFAULT_INTERIOR_VOCAB = (
    # Phase 8B 수정 — 인사말 예시 ("안녕하세요" 등) 제거.
    # medium 모델이 이 예시를 prior 로 잡아 짧은 음성에서
    # "감사합니다. 반갑습니다. 고맙습니다." 같은 인사 체인 환각을 만들었음.
    # 인사말 없이 도메인 어휘 중심으로만 시드.
    "다음은 한국어로 진행되는 인테리어 상담 녹음입니다. "
    "디자이너와 고객이 평수, 마감재, 조명, 견적 등 인테리어 전문 용어를 섞어 "
    "자연스러운 한국어 문장으로 대화합니다. "
    "유튜브 자막이나 영상 끝맺음이 아닌 실제 상담 대화입니다.\n"
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
# v3.0.0: 담당자(디자이너) 정보 — 카톡 문구 서명용
# ========================================
DESIGNER_DEFAULTS = {
    "name": "한승민",
    "store": "Livart&문테리어",
    "phone": "",
}


def get_designer_info(username: Optional[str] = None) -> Dict[str, str]:
    """
    담당자 정보 — v3.5.2: 사용자별 저장.
    username 주어지면 그 사용자의 user_settings 우선 → 없으면 글로벌 설정 → 없으면 기본값.
    이렇게 하면 기존 글로벌 값은 마이그레이션 없이 자동 폴백되어 호환됨.
    """
    return {
        "name":  _get_u(username, "designer.name")  or _get("designer.name")  or DESIGNER_DEFAULTS["name"],
        "store": _get_u(username, "designer.store") or _get("designer.store") or DESIGNER_DEFAULTS["store"],
        "phone": _get_u(username, "designer.phone") or _get("designer.phone") or DESIGNER_DEFAULTS["phone"],
    }


def set_designer_info(name: str, store: str, phone: str,
                      username: Optional[str] = None) -> Dict[str, str]:
    """v3.5.2: username 이 주어지면 그 사용자 전용으로 저장 (다른 사용자 영향 없음)."""
    name = (name or "").strip()
    store = (store or "").strip()
    phone = (phone or "").strip()
    if not name:
        raise ValueError("담당자 이름이 비어 있습니다.")
    if username:
        _set_u(username, "designer.name",  name)
        _set_u(username, "designer.store", store)
        _set_u(username, "designer.phone", phone)
    else:
        # 익명 호출(과거 코드 호환) 시에는 글로벌 저장
        _set("designer.name",  name)
        _set("designer.store", store)
        _set("designer.phone", phone)
    return {"name": name, "store": store, "phone": phone}


# ========================================
# v3.0.0 Phase 3: AI 분석 Ollama 모델 선택
# ========================================
def get_ollama_model() -> str:
    val = _get("ollama.model")
    return val if val else config.OLLAMA_MODEL


def set_ollama_model(model: str) -> None:
    model = (model or "").strip()
    if not model:
        raise ValueError("모델 이름이 비어 있습니다.")
    _set("ollama.model", model)


# ========================================
# v3.0.0 Phase 3: 상담별 추가 분석 항목
# 기본 스키마에 더해 사용자 정의 항목 추가 가능.
# 형식: [{"key": str, "label": str, "type": "list"|"text"}, ...]
# ========================================
_ANALYSIS_ITEM_TYPES = ("list", "text")


def get_analysis_extra_items(meeting_type: str) -> List[dict]:
    val = _get(f"analysis.extra_items.{meeting_type}")
    if val:
        try:
            data = json.loads(val)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def set_analysis_extra_items(meeting_type: str, items: List[dict]) -> List[dict]:
    if meeting_type not in config.MEETING_TYPES:
        raise ValueError(f"알 수 없는 상담 종류: {meeting_type}")
    validated: List[dict] = []
    seen: set = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip().replace(" ", "_")
        label = str(item.get("label", "")).strip()
        type_ = str(item.get("type", "list")).strip()
        if not key or not label:
            continue
        if type_ not in _ANALYSIS_ITEM_TYPES:
            type_ = "list"
        if key in seen:
            continue
        seen.add(key)
        validated.append({"key": key, "label": label, "type": type_})
    _set(f"analysis.extra_items.{meeting_type}", json.dumps(validated, ensure_ascii=False))
    return validated


# ========================================
# 한꺼번에 조회 (UI 용)
# ========================================
def get_all_settings(username: Optional[str] = None) -> Dict[str, Any]:
    """v3.5.2: username 이 주어지면 designer 등 사용자별 설정도 그 사용자 값으로 반환."""
    client_root = get_client_root()
    return {
        "whisper": {
            "model_size": get_whisper_model_size(),
            "beam_size": get_whisper_beam_size(),
            "model_choices": WHISPER_MODEL_CHOICES,
            "device": get_whisper_device(),                     # Phase 8B
            "device_choices": WHISPER_DEVICE_CHOICES,           # Phase 8B
            "last_post_model": get_last_post_model(),           # v2.5.0
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
        "designer": get_designer_info(username=username),    # v3.0.0 + v3.5.2 (per-user)
        "ollama": {                          # v3.0.0 Phase 3
            "model": get_ollama_model(),
            "default_model": config.OLLAMA_MODEL,
        },
        "analysis": {                        # v3.0.0 Phase 3
            "extra_items": {
                t: get_analysis_extra_items(t) for t in config.MEETING_TYPES
            },
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


# ========================================
# v3.5.2: 사용자별 설정 (user_settings 테이블)
# 글로벌 settings 와 분리해서 저장 — 같은 key 가 양쪽에 있으면 user_settings 가 우선.
# get_xxx 함수들은 _get_u(username, key) or _get(key) 식으로 폴백 체인 구성.
# ========================================

def _user_id_of(username: Optional[str]) -> Optional[int]:
    """username → user_id 변환. 없으면 None."""
    if not username:
        return None
    with db_cursor() as cur:
        row = cur.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    return row["id"] if row else None


def _get_u(username: Optional[str], key: str) -> Optional[str]:
    """user_settings 에서 (username, key) 값 조회. 없으면 None (호출자가 글로벌로 폴백)."""
    uid = _user_id_of(username)
    if uid is None:
        return None
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (uid, key),
        ).fetchone()
    return row["value"] if row else None


def _set_u(username: Optional[str], key: str, value: str) -> None:
    """user_settings 에 (username, key) → value 저장. username 모르면 무시 (오류 X)."""
    uid = _user_id_of(username)
    if uid is None:
        return  # 익명 호출은 무시 (호출자가 글로벌 _set 으로 폴백해야 함)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO user_settings(user_id, key, value) VALUES(?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (uid, key, value),
        )


# ========================================
# v3.5.3: Auth Server (중앙 계정 관리) 설정 — 글로벌 (PC 단위)
# 데스크톱: 자기가 서버일 때 enabled=True + api_key 생성
# 노트북:   자기가 클라이언트일 때 server_url + server_api_key 입력
# ========================================

import secrets as _secrets


def get_auth_server_enabled() -> bool:
    """이 PC 가 Auth Server 로 동작하는가."""
    return _get_bool("auth_server.enabled", False)


def set_auth_server_enabled(enabled: bool) -> None:
    _set_bool("auth_server.enabled", enabled)


def get_auth_server_api_key() -> str:
    """이 PC 가 서버일 때, 클라이언트가 인증할 때 보내야 하는 API 키. 없으면 새로 생성."""
    val = _get("auth_server.api_key")
    if val and len(val) >= 32:
        return val
    new_key = _secrets.token_hex(24)  # 48자 hex
    _set("auth_server.api_key", new_key)
    return new_key


def regenerate_auth_server_api_key() -> str:
    new_key = _secrets.token_hex(24)
    _set("auth_server.api_key", new_key)
    return new_key


def get_auth_server_url() -> str:
    """이 PC 가 클라이언트일 때, 호출할 Auth Server URL (예: http://100.64.1.5:8765)."""
    return _get("auth_server.url") or ""


def set_auth_server_url(url: str) -> None:
    _set("auth_server.url", (url or "").strip())


def get_auth_server_client_api_key() -> str:
    """이 PC 가 클라이언트일 때, 서버 호출에 사용할 API 키."""
    return _get("auth_server.client_api_key") or ""


def set_auth_server_client_api_key(key: str) -> None:
    _set("auth_server.client_api_key", (key or "").strip())


def is_auth_server_client() -> bool:
    """이 PC 가 Auth Server 의 클라이언트인지 (URL + API 키 둘 다 설정돼 있나)."""
    return bool(get_auth_server_url() and get_auth_server_client_api_key())
