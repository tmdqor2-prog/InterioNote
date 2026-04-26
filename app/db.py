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

CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name);
CREATE INDEX IF NOT EXISTS idx_meetings_client ON meetings(client_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_segments_meeting ON transcript_segments(meeting_id, start_ms);
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


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db_cursor() as cur:
        cur.executescript(SCHEMA_SQL)


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
