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
# 앱 버전 + 변경 이력 (Phase 6B)
# ========================================
# 새 기능/패치를 추가할 때 마다 버전을 올리고 CHANGELOG 맨 위에 항목을 추가하세요.
# 사용자가 '다시 열지 않기' 를 눌러도 버전이 바뀌면 시작 팝업이 다시 표시됩니다.
APP_VERSION = "2.3.0"

# GitHub 저장소 (Phase 7B-3 자동 업데이트 확인용)
# https://api.github.com/repos/{OWNER}/{REPO}/releases/latest 호출
# 설정 안 하려면 둘 중 하나를 빈 문자열로 두면 업데이트 확인 비활성화됨.
GITHUB_OWNER = "tmdqor2-prog"
GITHUB_REPO = "InterioNote"

CHANGELOG = [
    {
        "version": "2.3.0",
        "date": "2026-04-25",
        "title": "데이터 위치 분리 + 자동 업데이트 확인 + 앱 제거 안내",
        "items": [
            "사용자 데이터 위치를 %APPDATA%\\InterioNote\\ 로 분리 (앱 업데이트로부터 격리, 자동 마이그레이션 포함)",
            "설정 페이지에 📦 업데이트 확인 버튼 — 최신 여부 자동 체크 + 새 버전 발견 시 다운로드 페이지 안내",
            "설정 페이지에 🗑 앱 제거 안내 + 사용자 데이터 폴더 바로가기",
            "시작 팝업에 새 버전 발견 시 알림 배너",
        ],
    },
    {
        "version": "2.2.0",
        "date": "2026-04-25",
        "title": "기존 상담 다시 보기 + 오디오 재생",
        "items": [
            "고객 클릭 시 [신규 녹음 / 기존 상담 보기] 작업 선택 모달",
            "과거 상담 목록 — 일시·소요·카드수·AI분석 여부 표시, 클릭하면 다시 열림",
            "이전 상담 화면에서 🎧 녹음 재생 (브라우저 플레이어, 위치 이동·일시정지 가능)",
            "이전 상담의 화자 라벨 편집·재전사·AI 분석 모두 그대로 가능",
        ],
    },
    {
        "version": "2.1.0",
        "date": "2026-04-25",
        "title": "저장 위치·폴더 구조 사용자화 + 시작 팝업",
        "items": [
            "고객 폴더 루트 경로를 설정에서 변경 가능 (📂 찾아보기 다이얼로그 포함)",
            "신규 고객 자동 생성 서브폴더를 +/- 로 추가/삭제/편집",
            "앱 시작 시 환영·패치 노트 팝업 (버전 변경 시 자동 재표시)",
        ],
    },
    {
        "version": "2.0.0",
        "date": "2026-04-25",
        "title": "정확도 강화 + 설정 페이지",
        "items": [
            "Two-pass 재전사: 실시간 small + 종료 후 medium 으로 정확도 향상",
            "Whisper 반복 환각 자동 필터링 (매장 음악 환경 대응)",
            "노이즈 억제 (silero-denoise) — 설정에서 토글",
            "Whisper 모델·키워드 사전·VAD 임계값 사용자 설정 가능",
            "Ollama qwen2.5:3b 로 상담 종류별 AI 분석 (요약·체크리스트)",
        ],
    },
    {
        "version": "1.0.0",
        "date": "2026-04-22",
        "title": "초기 정식 출시",
        "items": [
            "고객별 자동 폴더 + MP3/WAV/대화전문.md/상담정보.json 저장",
            "실시간 한국어 녹음·전사 (Whisper + silero-vad)",
            "수동 화자 토글 (1=나 / 2=고객 / 0=지우기, 카드별 버튼)",
            "신규/기존 고객 분기 + 상담 종류 (초도/디자인/견적) 선택",
        ],
    },
]


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
