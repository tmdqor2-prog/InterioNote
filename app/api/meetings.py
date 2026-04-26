"""
상담(meetings) API.

- POST /api/meetings/new                            : 고객 + 상담종류 선택 후 meeting row 생성
- GET  /api/meetings?folder={folder_name}           : 고객 폴더로 과거 상담 목록 조회 (Phase 6C)
- GET  /api/meetings/{id}                           : 상담 메타 정보
- GET  /api/meetings/{id}/segments                  : 세그먼트 목록
- GET  /api/meetings/{id}/audio                     : MP3 스트리밍 (Phase 6C)
- POST /api/meetings/{id}/segments/{sid}/speaker    : 화자 라벨 변경
- POST /api/meetings/{id}/retranscribe              : Two-pass 재전사
"""
from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import config
from app.db import db_cursor
from app.services import (
    client_service,
    meeting_finalizer,
    retranscribe_service,
    settings_service,
)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _session_slug(started_at: datetime) -> str:
    return started_at.strftime("%Y%m%d_%H%M%S")


# ========================================
# POST /api/meetings/new
# ========================================
class NewMeetingRequest(BaseModel):
    folder_name: str = Field(..., min_length=1)
    meeting_type: str = Field(..., min_length=1)


@router.post("/new")
def new_meeting(req: NewMeetingRequest):
    # 상담 종류 검증
    if req.meeting_type not in config.MEETING_TYPES:
        raise HTTPException(
            400,
            f"알 수 없는 상담 종류: {req.meeting_type}. 허용: {config.MEETING_TYPES}",
        )

    # 폴더명 검증
    if "\\" in req.folder_name or "/" in req.folder_name:
        raise HTTPException(400, "유효하지 않은 폴더 이름입니다.")

    client_root = settings_service.get_client_root()
    folder_path = (client_root / req.folder_name).resolve()
    try:
        folder_path.relative_to(client_root.resolve())
    except ValueError:
        raise HTTPException(400, "고객 루트 바깥의 폴더입니다.")
    if not folder_path.exists():
        raise HTTPException(404, f"고객 폴더를 찾을 수 없습니다: {req.folder_name}")

    # 클라이언트 upsert
    try:
        client = client_service.upsert_client_by_folder(req.folder_name)
    except Exception as e:
        print(f"\n[new_meeting:upsert] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
        raise HTTPException(500, f"고객 정보 저장 실패: {type(e).__name__}: {e}")

    # 임시 폴더 경로 (녹음 중에만 사용, 종료 시 이동)
    started_at = datetime.now()
    temp_folder = config.TEMP_RECORDING_DIR / f"session_{_session_slug(started_at)}"

    # meeting row
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO meetings
                    (client_id, meeting_type, started_at, temp_folder, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (
                    client["id"],
                    req.meeting_type,
                    started_at.isoformat(timespec="seconds"),
                    str(temp_folder),
                ),
            )
            meeting_id = cur.lastrowid
    except Exception as e:
        print(f"\n[new_meeting:db] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
        raise HTTPException(500, f"상담 생성 실패: {type(e).__name__}: {e}")

    return {
        "meeting_id": meeting_id,
        "client_id": client["id"],
        "client_name": client["name"],
        "client_descriptor": client.get("descriptor"),
        "folder_name": req.folder_name,
        "folder_path": str(folder_path),
        "meeting_type": req.meeting_type,
        "started_at": started_at.isoformat(timespec="seconds"),
        "temp_folder": str(temp_folder),
        "status": "pending",
    }


# ========================================
# GET /api/meetings?folder={folder_name}
# 고객 폴더의 과거 상담 목록 (Phase 6C)
# ========================================
@router.get("")
def list_meetings_by_folder(folder: str):
    if not folder or "\\" in folder or "/" in folder:
        raise HTTPException(400, "유효하지 않은 폴더 이름입니다.")
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT m.id,
                   m.meeting_type,
                   m.started_at,
                   m.ended_at,
                   m.duration_sec,
                   m.status,
                   m.audio_file,
                   m.meeting_folder,
                   c.name AS client_name,
                   c.descriptor AS client_descriptor,
                   c.folder_name AS folder_name,
                   (SELECT COUNT(*) FROM transcript_segments WHERE meeting_id = m.id) AS segments_count,
                   (SELECT 1 FROM analyses WHERE meeting_id = m.id LIMIT 1) AS has_analysis
            FROM meetings m
            JOIN clients c ON c.id = m.client_id
            WHERE c.folder_name = ?
              AND m.meeting_folder IS NOT NULL
              AND m.status IN ('recorded', 'analyzing', 'done', 'failed')
            ORDER BY m.started_at DESC
            """,
            (folder,),
        ).fetchall()
    items = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        d["has_analysis"] = bool(d.get("has_analysis"))
        # 디스크 상에 mp3 가 실제로 있는지 표시 (이전 폴더 이동 등 검증)
        af = d.get("audio_file")
        d["audio_exists"] = bool(af and Path(af).exists())
        items.append(d)
    return {
        "folder_name": folder,
        "count": len(items),
        "meetings": items,
    }


# ========================================
# GET /api/meetings/{id}
# ========================================
@router.get("/{meeting_id}")
def get_meeting(meeting_id: int):
    with db_cursor() as cur:
        row = cur.execute(
            """
            SELECT m.*, c.name AS client_name, c.descriptor AS client_descriptor,
                   c.folder_name AS folder_name, c.folder_path AS folder_path
            FROM meetings m
            JOIN clients c ON c.id = m.client_id
            WHERE m.id = ?
            """,
            (meeting_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"meeting {meeting_id} not found")
    return {k: row[k] for k in row.keys()}


# ========================================
# GET /api/meetings/{id}/segments
# ========================================
@router.get("/{meeting_id}/segments")
def list_segments(meeting_id: int):
    return {"segments": meeting_finalizer.load_segments_from_db(meeting_id)}


# ========================================
# GET /api/meetings/{id}/audio
# 상담 폴더의 녹음.mp3 를 그대로 스트리밍 (Phase 6C)
# FastAPI FileResponse 가 Range 요청을 자동 처리 → 브라우저 audio 엘리먼트 seek 가능
# ========================================
@router.get("/{meeting_id}/audio")
def get_audio(meeting_id: int):
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT audio_file, meeting_folder FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"meeting {meeting_id} not found")

    audio_path: Optional[Path] = None
    if row["audio_file"]:
        candidate = Path(row["audio_file"])
        if candidate.exists():
            audio_path = candidate
    if audio_path is None and row["meeting_folder"]:
        candidate = Path(row["meeting_folder"]) / "녹음.mp3"
        if candidate.exists():
            audio_path = candidate
    if audio_path is None:
        raise HTTPException(404, "오디오 파일을 찾을 수 없습니다 (이동·삭제됐거나 경로 변경).")

    return FileResponse(
        str(audio_path),
        media_type="audio/mpeg",
        filename=audio_path.name,
    )


# ========================================
# POST /api/meetings/{id}/segments/{seg_id}/speaker
# ========================================
class SpeakerUpdateRequest(BaseModel):
    speaker: Optional[str] = None  # 'me' | 'client' | None


@router.post("/{meeting_id}/segments/{segment_id}/speaker")
def update_segment_speaker(
    meeting_id: int, segment_id: int, req: SpeakerUpdateRequest
):
    """
    녹음 완료 후 세그먼트의 화자 라벨 변경.
    DB 업데이트 + 대화전문.md 재생성.
    """
    if req.speaker not in (None, "me", "client"):
        raise HTTPException(400, f"invalid speaker: {req.speaker}")

    with db_cursor() as cur:
        row = cur.execute(
            "SELECT id FROM transcript_segments WHERE id = ? AND meeting_id = ?",
            (segment_id, meeting_id),
        ).fetchone()
        if row is None:
            raise HTTPException(
                404, f"segment {segment_id} not found in meeting {meeting_id}"
            )
        cur.execute(
            "UPDATE transcript_segments SET speaker = ? WHERE id = ?",
            (req.speaker, segment_id),
        )

    # 대화전문.md 재생성 (실패해도 DB 업데이트는 성공 상태)
    md_warning = None
    try:
        meeting_finalizer.regenerate_transcript_md(meeting_id)
    except Exception as e:
        import traceback as _tb
        md_warning = f"{type(e).__name__}: {e}"
        print(f"\n[regenerate_md] {md_warning}\n{_tb.format_exc()}", flush=True)

    return {
        "segment_id": segment_id,
        "speaker": req.speaker,
        "md_warning": md_warning,
    }


# ========================================
# POST /api/meetings/{id}/retranscribe
# Two-pass 후처리 — 더 큰 모델로 재전사
# ========================================
class RetranscribeRequest(BaseModel):
    model_size: Optional[str] = "medium"  # tiny / base / small / medium / large-v3


@router.post("/{meeting_id}/retranscribe")
def retranscribe(meeting_id: int, req: RetranscribeRequest):
    """
    녹음 종료 후 더 정확한 모델로 전체 WAV 재전사.
    transcript_segments 교체 + 대화전문.md 재생성.
    화자 라벨은 시간 겹침으로 자동 이관.
    """
    size = (req.model_size or "medium").strip()
    valid_sizes = ["tiny", "base", "small", "medium", "large-v3"]
    if size not in valid_sizes:
        raise HTTPException(400, f"허용되지 않는 모델: {size}. 가능: {valid_sizes}")
    try:
        result = retranscribe_service.retranscribe_meeting(
            meeting_id, model_size=size
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        import traceback as _tb
        print(
            f"\n[retranscribe] {type(e).__name__}: {e}\n{_tb.format_exc()}",
            flush=True,
        )
        raise HTTPException(
            500, f"재전사 실패 — {type(e).__name__}: {str(e)[:400]}"
        )
    return result
