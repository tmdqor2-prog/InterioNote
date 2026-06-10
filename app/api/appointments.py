"""
v3.5.0 ④ — 고객 일정 관리 API.

GET    /api/appointments              : 오늘·이번 주 예정 일정 (홈 위젯용)
GET    /api/clients/{id}/appointments : 고객별 일정 목록
POST   /api/clients/{id}/appointments : 일정 추가
PATCH  /api/appointments/{id}        : 일정 수정 / 완료 처리
DELETE /api/appointments/{id}        : 일정 삭제
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.db import db_cursor

router = APIRouter(tags=["appointments"])


# ─── 모델 ─────────────────────────────────────────────────────────────────────

class AppointmentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    scheduled_at: str = Field(...)   # "YYYY-MM-DD HH:MM" 또는 "YYYY-MM-DD"
    notes: Optional[str] = None


class AppointmentUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    scheduled_at: Optional[str] = None
    notes: Optional[str] = None
    completed: Optional[bool] = None


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _row(r) -> dict:
    d = dict(r)
    # D-day 계산
    try:
        scheduled = datetime.fromisoformat(d["scheduled_at"])
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        diff = (scheduled.replace(hour=0, minute=0, second=0, microsecond=0) - today).days
        d["dday"] = diff  # 음수=지남, 0=오늘, 양수=앞으로
    except Exception:
        d["dday"] = None
    return d


# ─── 엔드포인트 ───────────────────────────────────────────────────────────────

@router.get("/api/appointments")
def upcoming_appointments():
    """오늘 이후 모든 예정 일정 (홈 화면 위젯용, 30일 이내 우선)."""
    now_str = datetime.now().strftime("%Y-%m-%d")
    limit_str = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT a.*, c.name as client_name, c.phone as client_phone, c.id as client_db_id
            FROM appointments a
            JOIN clients c ON c.id = a.client_id
            WHERE a.completed = 0
              AND date(a.scheduled_at) >= ?
              AND date(a.scheduled_at) <= ?
            ORDER BY a.scheduled_at
            """,
            (now_str, limit_str),
        ).fetchall()
    return [_row(r) for r in rows]


@router.get("/api/appointments/recently-completed")
def recently_completed_appointments():
    """최근 3일 내 완료된 일정 (홈 화면 '완료 일정' 섹션용)."""
    three_days_ago = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT a.*, c.name as client_name, c.id as client_db_id
            FROM appointments a
            JOIN clients c ON c.id = a.client_id
            WHERE a.completed = 1
              AND a.completed_at IS NOT NULL
              AND a.completed_at >= ?
            ORDER BY a.completed_at DESC
            """,
            (three_days_ago,),
        ).fetchall()
    return [_row(r) for r in rows]


@router.get("/api/clients/{client_id}/appointments")
def client_appointments(client_id: int):
    """고객별 일정 목록 (완료 포함, 최신순)."""
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT a.*, c.name as client_name
            FROM appointments a
            JOIN clients c ON c.id = a.client_id
            WHERE a.client_id = ?
            ORDER BY a.scheduled_at DESC
            """,
            (client_id,),
        ).fetchall()
    return [_row(r) for r in rows]


@router.post("/api/clients/{client_id}/appointments", status_code=201)
def create_appointment(client_id: int, req: AppointmentCreate):
    with db_cursor() as cur:
        # 고객 존재 확인
        c = cur.execute("SELECT id FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not c:
            raise HTTPException(404, "고객을 찾을 수 없습니다.")
        cur.execute(
            "INSERT INTO appointments(client_id, title, scheduled_at, notes) "
            "VALUES(?, ?, ?, ?)",
            (client_id, req.title, req.scheduled_at, req.notes),
        )
        row = cur.execute(
            "SELECT a.*, c.name as client_name FROM appointments a "
            "JOIN clients c ON c.id = a.client_id "
            "WHERE a.id = last_insert_rowid()"
        ).fetchone()
    return _row(row)


@router.patch("/api/appointments/{appt_id}")
def update_appointment(appt_id: int, req: AppointmentUpdate):
    with db_cursor() as cur:
        row = cur.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        if not row:
            raise HTTPException(404, "일정을 찾을 수 없습니다.")
        if req.title is not None:
            cur.execute("UPDATE appointments SET title = ? WHERE id = ?", (req.title, appt_id))
        if req.scheduled_at is not None:
            cur.execute("UPDATE appointments SET scheduled_at = ? WHERE id = ?", (req.scheduled_at, appt_id))
        if req.notes is not None:
            cur.execute("UPDATE appointments SET notes = ? WHERE id = ?", (req.notes, appt_id))
        if req.completed is not None:
            cur.execute("UPDATE appointments SET completed = ? WHERE id = ?", (1 if req.completed else 0, appt_id))
            if req.completed:
                # 완료 처리 시각 기록 (3일 내 최근 완료 표시에 사용)
                cur.execute(
                    "UPDATE appointments SET completed_at = ? WHERE id = ?",
                    (datetime.now().isoformat(timespec="seconds"), appt_id),
                )
        updated = cur.execute(
            "SELECT a.*, c.name as client_name FROM appointments a "
            "JOIN clients c ON c.id = a.client_id WHERE a.id = ?", (appt_id,)
        ).fetchone()
    return _row(updated)


@router.delete("/api/appointments/{appt_id}")
def delete_appointment(appt_id: int):
    with db_cursor() as cur:
        cur.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
    return {"ok": True}
