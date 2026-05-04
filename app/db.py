"""
SQLite DB 초기화 + 커넥션 헬퍼.
Phase 1에서 모든 테이블을 IF NOT EXISTS로 만들고, 이후 Phase에서 그대로 사용.
"""
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

from app.config import DB_PATH

SCHEMA_SQL = """
-- 고객: 07_고객정보 폴더의 실제 폴더에 1:1 매핑
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                -- "김경호"
    descriptor TEXT,                    -- "dmc래미안_26평" (괄호 내부)
    folder_name TEXT UNIQUE NOT NULL,  -- "김경호 고객님(dmc래미안_26평)"
    folder_path TEXT UNIQUE NOT NULL,  -- 절대경로
    first_met_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- 상담: 한 고객에 여러 건 (초도상담/디자인미팅/견적미팅)
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    meeting_type TEXT NOT NULL,
    started_at DATETIME NOT NULL,
    ended_at DATETIME,
    duration_sec INTEGER,
    meeting_folder TEXT,               -- 상담별 날짜 폴더 경로
    audio_file TEXT,                   -- 최종 MP3 경로
    temp_folder TEXT,                  -- 녹음 중 임시 경로
    status TEXT DEFAULT 'recording',   -- recording|recorded|analyzing|done|failed
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

-- 전사 세그먼트 (VAD가 쪼갠 발화 단위)
CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    speaker TEXT,                      -- 'me'|'client'|NULL (녹음 후 수동 라벨)
    confidence REAL,
    -- Phase 8A: 사용자가 직접 수정한 카드는 edited_at 이 채워짐.
    -- 재전사(retranscribe) 가 동일 시간대의 새 카드를 만들어도 이 카드는 보존됨.
    edited_at DATETIME,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
);

-- AI 분석 결과 (상담 종류별 JSON 스키마)
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER UNIQUE NOT NULL,
    data_json TEXT NOT NULL,
    model_used TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
);

-- 설정 (키/값)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Phase 8B+: 재전사 직전 스냅샷 (되돌리기용)
-- meeting_id 당 1개만 보관 (최신 1단계 undo). 새 재전사 시 기존 스냅샷 덮어씀.
CREATE TABLE IF NOT EXISTS transcript_snapshots (
    meeting_id INTEGER PRIMARY KEY,
    snapshot_json TEXT NOT NULL,        -- JSON list of segment dicts
    label TEXT,                          -- 'pre_retranscribe' 등
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
);

-- v2.6.0 K: 태그 시스템 (상담별 다중 태그)
CREATE TABLE IF NOT EXISTS meeting_tags (
    meeting_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (meeting_id, tag),
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
);

-- v2.6.0 Q: 빠른 답변 템플릿 (자주 쓰는 안내 문구)
CREATE TABLE IF NOT EXISTS quick_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- v3.0.0 Phase 2: 사용자 계정 (로그인 + 권한 관리)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,        -- 로그인 아이디 (영문·숫자·_)
    display_name TEXT NOT NULL,           -- 표시 이름 (예: 한승민)
    password_hash TEXT NOT NULL,          -- bcrypt 해시
    role TEXT NOT NULL DEFAULT 'user',    -- 'master' | 'user'
    is_active INTEGER NOT NULL DEFAULT 1, -- 0 이면 로그인 불가
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- v3.5.0 ④: 고객 일정 (약속·미팅 예약)
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    title TEXT NOT NULL,             -- 예: "디자인미팅", "현장실측"
    scheduled_at DATETIME NOT NULL,  -- 예약 일시
    notes TEXT,                       -- 비고
    completed INTEGER DEFAULT 0,     -- 0=예정, 1=완료
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

-- v3.0.0 Phase 3: 팔로업 템플릿 (상담 종류별 후속 메시지)
-- 변수: {{고객명}} {{담당자}} {{매장명}} {{날짜}} {{분석요약}}
CREATE TABLE IF NOT EXISTS followup_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_type TEXT NOT NULL,     -- '초도상담'|'디자인미팅'|'견적미팅'|'all'
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- v3.5.2: 계정별 설정 (담당자 정보·OJT 매핑·견적서 양식 등 사용자별로 달라야 하는 값)
-- 글로벌 settings 테이블은 PC 전체 설정 (whisper 모델 / VAD / 폴더 경로 등) 으로 유지.
-- 같은 key 가 양쪽에 있으면 user_settings 가 우선 (settings_service._get_u 가 fallback 처리).
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (user_id, key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name);
CREATE INDEX IF NOT EXISTS idx_meetings_client ON meetings(client_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_segments_meeting ON transcript_segments(meeting_id, start_ms);
CREATE INDEX IF NOT EXISTS idx_meeting_tags_tag ON meeting_tags(tag);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_cursor() -> Iterator[sqlite3.Cursor]:
    conn = get_conn()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_schema(cur: sqlite3.Cursor) -> None:
    """기존 DB 의 누락 컬럼을 순차적으로 ADD COLUMN.
    SQLite 는 새 컬럼이 이미 있으면 OperationalError 던지니까 catch 로 idempotent."""
    migrations = [
        # Phase 8A: 사용자 카드 편집 추적
        ("transcript_segments", "edited_at",
         "ALTER TABLE transcript_segments ADD COLUMN edited_at DATETIME"),
        # v2.5.1: 상담 자유 메모 (녹음 외 디자이너가 따로 적는 내용)
        ("meetings", "notes",
         "ALTER TABLE meetings ADD COLUMN notes TEXT"),
        # v2.6.0 L: 계약 진행률 (초도/디자인/견적/계약/시공/완료)
        ("clients", "stage",
         "ALTER TABLE clients ADD COLUMN stage TEXT DEFAULT '초도'"),
        # v2.6.0 P: 즐겨찾기 고객
        ("clients", "is_favorite",
         "ALTER TABLE clients ADD COLUMN is_favorite INTEGER DEFAULT 0"),
        # v2.6.0 P: 마지막 상담 일자 (정렬·표시용 캐시)
        ("clients", "last_meeting_at",
         "ALTER TABLE clients ADD COLUMN last_meeting_at DATETIME"),
        # v2.6.0 JJ: OJT 동기화 추적 (이미 동기화한 상담은 중복 안 함)
        ("meetings", "ojt_synced_at",
         "ALTER TABLE meetings ADD COLUMN ojt_synced_at DATETIME"),
        # v3.0.0 Phase 1: 고객 연락처 + 방문 경로
        ("clients", "phone",
         "ALTER TABLE clients ADD COLUMN phone TEXT"),
        ("clients", "email",
         "ALTER TABLE clients ADD COLUMN email TEXT"),
        ("clients", "visit_source",
         "ALTER TABLE clients ADD COLUMN visit_source TEXT"),
        # v3.2.0 Phase 4: 준비 노트 (상담 전 메모)
        ("meetings", "pre_notes",
         "ALTER TABLE meetings ADD COLUMN pre_notes TEXT"),
        # v3.3.0 Phase 5: 회원가입 승인 상태 ('active'|'pending')
        ("users", "status",
         "ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'"),
        # v3.5.0 ②: 고객 커스텀 필드 (JSON)
        ("clients", "custom_fields",
         "ALTER TABLE clients ADD COLUMN custom_fields TEXT"),
        # v3.5.0 ③: 소개 경로 (다른 고객 ID)
        ("clients", "referred_by_client_id",
         "ALTER TABLE clients ADD COLUMN referred_by_client_id INTEGER"),
        # v3.5.0 ⑮: 계약 금액 + 입금 + 계약일
        ("meetings", "contract_amount",
         "ALTER TABLE meetings ADD COLUMN contract_amount REAL"),
        ("meetings", "deposit_amount",
         "ALTER TABLE meetings ADD COLUMN deposit_amount REAL"),
        ("meetings", "contract_date",
         "ALTER TABLE meetings ADD COLUMN contract_date TEXT"),
        # v3.5.0 (fix): 소개 경로 자유 텍스트 (DB 고객 외 소개자)
        ("clients", "referral_name",
         "ALTER TABLE clients ADD COLUMN referral_name TEXT"),
        # v3.5.0 (fix): 일정 완료 시각 (최근 완료 표시용)
        ("appointments", "completed_at",
         "ALTER TABLE appointments ADD COLUMN completed_at DATETIME"),
        # v3.5.2: 사용자별 원격 Ollama URL (마스터가 본인 데스크톱 활용 시 사용)
        # 예: "http://100.64.1.5:11434" (Tailscale IP)
        # 비어 있으면 로컬(localhost:11434) 사용 → 일반 사용자 영향 없음
        ("users", "ollama_remote_url",
         "ALTER TABLE users ADD COLUMN ollama_remote_url TEXT"),
        # v3.5.3: 원격 Auth Server 에서 동기화된 사용자 표시
        # 0 = 로컬 가입자 (이 PC 에서 직접 추가됨)
        # 1 = Auth Server 에서 캐시된 사용자 (다른 PC 에서 가입, 동기화로 들어옴)
        ("users", "from_auth_server",
         "ALTER TABLE users ADD COLUMN from_auth_server INTEGER DEFAULT 0"),
    ]
    for table, column, sql in migrations:
        try:
            cur.execute(sql)
        except sqlite3.OperationalError as e:
            # "duplicate column name" 이면 이미 마이그레이션 됨
            if "duplicate column" not in str(e).lower():
                raise


_DEFAULT_FOLLOWUP_TEMPLATES = [
    # ─ 초도상담 ──────────────────────────────────────────────────────────────
    ("초도상담",   "초도상담 감사 인사",
     "안녕하세요, {{고객명}} 고객님 😊\n오늘 {{매장명}} 방문해 주셔서 감사합니다.\n"
     "말씀 주신 내용 꼼꼼히 메모해 두었고, 실측 일정을 잡아 디자인 제안 드릴게요.\n"
     "편하신 날짜 알려 주시면 바로 조율하겠습니다!\n\n{{담당자}} 드림"),
    ("초도상담",   "실측 일정 제안",
     "안녕하세요, {{고객명}} 고객님!\n저번에 말씀 나눈 {{담당자}}입니다 😊\n"
     "실측 날짜를 잡으려고 연락드렸어요.\n"
     "방문 가능하신 날짜·시간대를 알려 주시면 맞춰서 찾아뵙겠습니다!\n"
     "평일 오전 / 오후 중 편하신 때 말씀해 주세요."),
    ("초도상담",   "자료 전달 안내",
     "안녕하세요, {{고객명}} 고객님 😊\n오늘 상담에서 말씀 드린 참고 자료 공유드립니다.\n"
     "확인하시고 궁금하신 점은 언제든지 연락 주세요!\n\n{{담당자}} — {{매장명}}"),
    # ─ 디자인미팅 ────────────────────────────────────────────────────────────
    ("디자인미팅", "디자인미팅 감사 인사",
     "안녕하세요, {{고객명}} 고객님 😊\n오늘 디자인 미팅 함께해 주셔서 감사합니다.\n"
     "수정 사항 반영해서 견적서 준비해 드리겠습니다.\n"
     "궁금하신 점 언제든지 말씀해 주세요!\n\n{{담당자}} 드림"),
    ("디자인미팅", "디자인 확정 확인 요청",
     "안녕하세요, {{고객명}} 고객님!\n지난번 보여드린 디자인 방향 검토해 보셨나요? 😊\n"
     "추가 수정이 필요하시거나 방향이 맞으시면 말씀 주시면,\n"
     "바로 견적서 작업 들어가겠습니다!\n\n{{담당자}} — {{매장명}}"),
    # ─ 견적미팅 ──────────────────────────────────────────────────────────────
    ("견적미팅",   "견적미팅 감사 인사",
     "안녕하세요, {{고객명}} 고객님 😊\n오늘 견적 상담 시간 내어 주셔서 감사합니다.\n"
     "계약 관련 추가 문의 사항이 있으시면 편하게 연락 주세요.\n"
     "좋은 결과로 보답드리겠습니다!\n\n{{담당자}} 드림"),
    ("견적미팅",   "견적서 전달 안내",
     "안녕하세요, {{고객명}} 고객님!\n오늘 말씀드린 견적서 파일을 공유드립니다 😊\n"
     "항목별 문의사항은 언제든 주세요. 감사합니다!\n\n{{담당자}} — {{매장명}}"),
    ("견적미팅",   "계약 완료 환영",
     "안녕하세요, {{고객명}} 고객님 🎉\n계약해 주셔서 진심으로 감사드립니다!\n"
     "공사 일정 확정되는 대로 다시 연락 드릴게요.\n"
     "마음에 드시는 공간이 완성될 수 있도록 최선을 다하겠습니다!\n\n{{담당자}} — {{매장명}}"),
    # ─ 공통 ──────────────────────────────────────────────────────────────────
    ("all",        "안부 + 재방문 유도",
     "안녕하세요, {{고객명}} 고객님 😊\n저번에 상담 후 잘 지내고 계신가요?\n"
     "인테리어 관련해서 새로 생긴 소식이 있어 연락드렸어요.\n"
     "궁금하신 게 있으시면 편하게 연락 주세요!\n\n{{담당자}} — {{매장명}}"),
]


def _ensure_default_followup_templates(cur) -> None:
    """팔로업 템플릿 기본값 — 테이블이 비어 있을 때만 삽입."""
    existing = cur.execute("SELECT COUNT(*) as cnt FROM followup_templates").fetchone()
    if existing["cnt"] > 0:
        return
    for meeting_type, title, content in _DEFAULT_FOLLOWUP_TEMPLATES:
        cur.execute(
            "INSERT INTO followup_templates(meeting_type, title, content) VALUES(?, ?, ?)",
            (meeting_type, title, content),
        )


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db_cursor() as cur:
        cur.executescript(SCHEMA_SQL)
        _migrate_schema(cur)
        _ensure_default_followup_templates(cur)


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
