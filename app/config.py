"""
InterioNote - 전역 설정
실제 운영 환경의 고정된 경로와 기본값.
"""
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger("config")

# ========================================
# 프로젝트 경로 (앱 코드 위치)
# - 개발: C:\InterioNote\
# - .exe (PyInstaller, Phase 7B): _MEIPASS 임시 디렉터리
# ========================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ========================================
# 사용자 데이터 디렉터리 (Phase 7A — .exe 배포 대비)
# Windows:
#   %APPDATA%\InterioNote\        ← 영구 데이터 (DB)
#   %LOCALAPPDATA%\InterioNote\   ← 캐시 (모델, 임시 녹음)
# 다른 OS / 환경:
#   ~/.interionote / ~/.cache/interionote
# 환경변수 INTERIONOTE_DATA_DIR / INTERIONOTE_CACHE_DIR 로 오버라이드 가능 (테스트용)
# ========================================
def _default_user_data_dir() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "InterioNote"
    return Path.home() / ".interionote"


def _default_user_cache_dir() -> Path:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "InterioNote"
    return Path.home() / ".cache" / "interionote"


USER_DATA_DIR = Path(
    os.environ.get("INTERIONOTE_DATA_DIR") or _default_user_data_dir()
)
USER_CACHE_DIR = Path(
    os.environ.get("INTERIONOTE_CACHE_DIR") or _default_user_cache_dir()
)

DATA_DIR = USER_DATA_DIR / "data"
DB_PATH = DATA_DIR / "interionote.db"
MODELS_CACHE_DIR = USER_CACHE_DIR / "models_cache"
TEMP_RECORDING_DIR = USER_CACHE_DIR / "temp_recording"

# ========================================
# 고객 폴더 루트 (settings 에서 변경 가능 — Phase 6A)
# 이 값은 fallback 기본값. 실제 동작은 settings_service.get_client_root() 통해.
# ========================================
CLIENT_ROOT = Path(
    r"C:\Users\b0463\Documents\Livart&문테리어\07_고객정보"
)

# ========================================
# 앱 버전 + 변경 이력 (v2.4.2 부터 version.json 으로 분리)
# ========================================
# Phase 8D 빠른 업데이트가 _internal/app/version.json 을 교체할 수 있도록
# 단순 데이터 파일로 관리. config.py 는 그걸 읽기만 함.
# 수정 시: app/version.json 만 편집. 절대 이 .py 안에 버전을 다시 박지 마세요.
def _load_version_info() -> dict:
    """version.json 을 읽어 버전·CHANGELOG 반환. PyInstaller 번들/dev 양쪽 대응."""
    import json as _json
    import sys as _sys
    candidates = []
    # 1) PyInstaller 번들 (--onedir): _internal/app/version.json
    meipass = getattr(_sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "app" / "version.json")
    # 2) dev 모드: app/version.json (이 파일 옆)
    candidates.append(Path(__file__).resolve().parent / "version.json")
    for p in candidates:
        try:
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    return _json.load(f)
        except Exception:
            continue
    # fallback (절대 일어나면 안 되지만 안전망)
    return {"version": "0.0.0", "changelog": []}


_VERSION_INFO = _load_version_info()
APP_VERSION = _VERSION_INFO.get("version") or "0.0.0"

# GitHub 저장소 (Phase 7B-3 자동 업데이트 확인용)
# https://api.github.com/repos/{OWNER}/{REPO}/releases/latest 호출
# 설정 안 하려면 둘 중 하나를 빈 문자열로 두면 업데이트 확인 비활성화됨.
GITHUB_OWNER = "tmdqor2-prog"
GITHUB_REPO = "InterioNote"

CHANGELOG = _VERSION_INFO.get("changelog") or []


# ========================================
# 앱 창 (pywebview)
# ========================================
WINDOW_TITLE = "InterioNote"
WINDOW_SIZE = (1280, 900)
WINDOW_MIN_SIZE = (1000, 700)

# ========================================
# 상담 유형 (3종 고정)
# ========================================
MEETING_TYPES = ["초도상담", "디자인미팅", "견적미팅"]

# ========================================
# Whisper STT 설정
# ========================================
# tiny / base / small / medium / large-v3
# - small: 한국어 정확도 충분, 460MB, CPU 실시간 OK (권장)
# - base: 가벼움(140MB) 이지만 한국어 정확도가 낮음
# - medium: 더 정확하지만 1.5GB + CPU에서 실시간 어려움
WHISPER_MODEL_SIZE = "small"
# beam_size: 1=가장 빠름/정확도 낮음, 5=권장, 8=더 정확하지만 느림
WHISPER_BEAM_SIZE = 5

# ========================================
# Ollama (Phase 4 - AI 분석)
# ========================================
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:3b"
OLLAMA_TIMEOUT_SEC = 600  # 10분 (CPU 분석 여유)
# 전사 토큰이 너무 길면 맨 앞/뒤는 유지하고 중간을 자르는 truncation 임계
OLLAMA_MAX_TRANSCRIPT_CHARS = 18000

# ========================================
# 고객 폴더 템플릿
# 기존 고객 폴더에서 실제 확인된 서브폴더명 + 상담기록 폴더
# ========================================
FOLDER_TEMPLATE = [
    "ETC",
    "렌더이미지_요청",
    "제안서 관련",
    "현장 이미지",
    "휴지통",
    "상담기록",  # InterioNote 출력 전용
]

# ========================================
# v2.6.0 L: 계약 진행률 단계
# ========================================
CLIENT_STAGES = ["초도", "디자인", "견적", "계약", "시공", "완료"]
CLIENT_STAGE_DEFAULT = "초도"

# ========================================
# v2.6.0 K: 추천 태그 (자동완성 시드)
# 디자이너가 직접 추가하면 누적 학습됨
# ========================================
DEFAULT_TAG_SUGGESTIONS = [
    "확장", "비확장", "올수리", "부분수리",
    "화이트톤", "우드톤", "모던", "내추럴", "클래식",
    "예산상", "예산중", "예산하",
    "신혼", "분양", "투자",
    "주방단품", "욕실단품", "필름시공",
]

# ========================================
# v2.6.0 JJ: OJT 매핑 — 신규 고객 초도상담 전용
# 사용자별 OJT 양식이 다르므로 settings DB 의
#   ojt.file_path  (str)
#   ojt.column_mapping  (JSON dict)
# 두 키를 마법사로 받음. 아래는 InterioNote 가 제공할 수 있는 "필드" 목록.
# ========================================
OJT_FIELD_KEYS = [
    "consult_date",   # 상담 일자
    "name",           # 고객명
    "phone",          # 연락처
    "address",        # 주소
    "construction",   # 공사 내용
    "size",           # 평형
    "budget",         # 예산
    "measure_date",   # 실측일
    "probability",    # A/B/C 진행 확률
    "memo",           # 비고/메모
]
OJT_FIELD_LABELS = {
    "consult_date": "상담 일자",
    "name": "고객명",
    "phone": "연락처",
    "address": "주소",
    "construction": "공사 내용",
    "size": "평형/면적",
    "budget": "예산",
    "measure_date": "실측일",
    "probability": "진행 확률 (A/B/C)",
    "memo": "비고/메모",
}

# ========================================
# v2.8.0 FF: 견적서 자동 작성
# 사용자가 자기 견적서 양식을 템플릿으로 등록.
# 가장 자주 쓰는 셀 (고객명/연락처/주소/공사기간/담당자/평형) 을
# AI 분석 결과의 site_info 와 매핑해서 자동 채움.
# 실제 견적 항목 (자재비/인건비) 은 사용자가 검토 후 입력.
# ========================================
QUOTE_FIELD_KEYS = [
    "client_name",      # 고객명
    "client_phone",     # 연락처
    "site_address",     # 공사현장 주소
    "construction_period",  # 공사기간
    "designer_name",    # 담당자
    "size_pyeong",      # 평형
    "size_m2",          # 면적 m²
    "quote_date",       # 견적일
    "construction_type",# 공사 종류 (전체/주방/욕실/필름 등)
    "memo",             # 비고
]
QUOTE_FIELD_LABELS = {
    "client_name": "고객명",
    "client_phone": "연락처",
    "site_address": "공사현장 주소",
    "construction_period": "공사기간",
    "designer_name": "담당자",
    "size_pyeong": "평형",
    "size_m2": "면적 (m²)",
    "quote_date": "견적일",
    "construction_type": "공사 종류",
    "memo": "비고",
}

# ========================================
# 초기화
# ========================================
def ensure_dirs() -> None:
    """앱 기동 시 필수 폴더 생성. 마이그레이션 전에 호출."""
    for d in (USER_DATA_DIR, USER_CACHE_DIR, DATA_DIR, MODELS_CACHE_DIR, TEMP_RECORDING_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ========================================
# Phase 7A: Legacy 마이그레이션
# 이전 위치의 데이터/모델 캐시를 새 위치로 이전.
# - DB: COPY (안전. 옛 파일은 백업으로 남김)
# - 모델 캐시: MOVE (대용량, 중복 보관 비효율)
# - 임시 녹음: 무시 (휘발성)
# 새 위치에 이미 데이터가 있으면 스킵 (중복 마이그레이션 방지).
# ========================================
LEGACY_PROJECT_DATA_DIR = PROJECT_ROOT / "data"
LEGACY_PROJECT_MODELS_DIR = PROJECT_ROOT / "models_cache"
LEGACY_TEMP_DIR = Path(r"C:\InterioNote_temp")


def migrate_legacy_data() -> dict:
    """
    한 번만 실행되어도 안전한 idempotent 함수.
    반환: {"migrated": [...], "skipped": [...], "errors": [...]}
    """
    result = {"migrated": [], "skipped": [], "errors": []}

    # ---- DB 복사 ----
    legacy_db = LEGACY_PROJECT_DATA_DIR / "interionote.db"
    if legacy_db.exists():
        if not DB_PATH.exists():
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(legacy_db), str(DB_PATH))
                # WAL/SHM 사이드카 파일도 같이 복사
                for ext in ("-wal", "-shm"):
                    sidecar = legacy_db.parent / (legacy_db.name + ext)
                    if sidecar.exists():
                        shutil.copy2(str(sidecar), str(DB_PATH) + ext)
                result["migrated"].append(f"DB → {DB_PATH}")
                log.info(f"DB migrated: {legacy_db} -> {DB_PATH}")
            except Exception as e:
                err = f"DB 복사 실패: {type(e).__name__}: {e}"
                result["errors"].append(err)
                log.error(err)
        else:
            result["skipped"].append("DB (새 위치에 이미 존재)")

    # ---- 모델 캐시 이동 ----
    if LEGACY_PROJECT_MODELS_DIR.exists():
        new_has_data = MODELS_CACHE_DIR.exists() and any(MODELS_CACHE_DIR.iterdir())
        if not new_has_data:
            try:
                # 새 디렉터리가 빈 채로 만들어져 있으면 비우고 통째로 옮김
                if MODELS_CACHE_DIR.exists():
                    try:
                        MODELS_CACHE_DIR.rmdir()  # 빈 폴더만 삭제됨
                    except OSError:
                        pass
                MODELS_CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(LEGACY_PROJECT_MODELS_DIR), str(MODELS_CACHE_DIR))
                result["migrated"].append(f"모델 캐시 → {MODELS_CACHE_DIR}")
                log.info(
                    f"models moved: {LEGACY_PROJECT_MODELS_DIR} -> {MODELS_CACHE_DIR}"
                )
            except Exception as e:
                err = f"모델 캐시 이동 실패: {type(e).__name__}: {e}"
                result["errors"].append(err)
                log.error(err)
        else:
            result["skipped"].append("모델 캐시 (새 위치에 이미 데이터 있음)")

    # 마이그레이션 로그 누적 기록 (디버깅·추적용)
    if result["migrated"] or result["errors"]:
        try:
            marker = USER_DATA_DIR / "MIGRATED_FROM_LEGACY.txt"
            existing = marker.read_text(encoding="utf-8") if marker.exists() else ""
            new_text = (
                f"--- {datetime.now().isoformat(timespec='seconds')} ---\n"
                + ("\n".join(result["migrated"] + result["errors"]) or "(nothing)")
                + "\n\n"
            )
            marker.write_text(existing + new_text, encoding="utf-8")
        except Exception:
            pass

    return result


def persist_client_root_default() -> None:
    """
    Phase 7A 보호 장치:
    사용자가 Phase 6A 설정 UI 로 client_root 를 명시적으로 바꾼 적 없으면
    현재 config.CLIENT_ROOT 를 settings DB 에 저장.
    이렇게 해두면 나중에 distribution 용으로 default 가 generic 으로 바뀌어도
    이 PC 의 사용자는 자기 경로를 그대로 유지함.
    """
    try:
        from app.services import settings_service as ss
        existing = ss._get("paths.client_root")
        if existing:
            return
        if CLIENT_ROOT.exists():
            ss.set_client_root(str(CLIENT_ROOT))
            log.info(f"persisted client_root: {CLIENT_ROOT}")
    except Exception as e:
        log.warning(f"persist_client_root_default failed: {type(e).__name__}: {e}")
