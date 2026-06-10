"""
녹음 API (Phase 2).
- GET  /api/audio/devices
- POST /api/recording/warmup          (VAD + Whisper 모델 사전 로드)
- POST /api/recording/start           {device_id?}
- POST /api/recording/stop
- GET  /api/recording/state
- GET  /api/recording/segments?since= (보조 폴링)
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import config
from app.db import db_cursor
from app.services import (
    audio_recorder,
    live_session,
    meeting_finalizer,
    noise_suppression_service,
    settings_service,
    vad_service,
    whisper_service,
)

log = logging.getLogger("api.recording")
router = APIRouter(prefix="/api", tags=["recording"])


def _describe_exc(prefix: str, e: Exception) -> str:
    print(f"\n[{prefix}] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
    return f"{type(e).__name__}: {str(e)[:400]}"


# ----------------------------------------
# Device listing
# ----------------------------------------
@router.get("/audio/devices")
def audio_devices():
    try:
        return {"devices": audio_recorder.list_input_devices()}
    except Exception as e:
        raise HTTPException(500, _describe_exc("audio_devices", e))


# ----------------------------------------
# Warmup
# ----------------------------------------
class WarmupResponse(BaseModel):
    vad_loaded: bool
    whisper_loaded: bool
    whisper_size: str
    noise_suppression_enabled: bool
    noise_suppression_loaded: bool
    noise_suppression_error: Optional[str] = None


@router.post("/recording/warmup", response_model=WarmupResponse)
def warmup():
    """silero VAD + faster-whisper (+ DeepFilterNet 옵션) 을 미리 로드."""
    try:
        vad_service.get_vad_model()
    except Exception as e:
        raise HTTPException(500, f"VAD 로드 실패 - {_describe_exc('warmup_vad', e)}")
    try:
        whisper_service.get_whisper()
    except Exception as e:
        raise HTTPException(500, f"Whisper 로드 실패 - {_describe_exc('warmup_whisper', e)}")

    # 노이즈 억제: 토글이 켜져 있으면 미리 로드. 실패해도 본 흐름은 막지 않음.
    noise_enabled = settings_service.get_noise_suppression_enabled()
    noise_loaded = False
    noise_err: Optional[str] = None
    if noise_enabled:
        try:
            noise_suppression_service.warmup()
            noise_loaded = noise_suppression_service.is_loaded()
        except Exception as e:
            noise_err = _describe_exc("warmup_noise", e)

    return WarmupResponse(
        vad_loaded=True,
        whisper_loaded=whisper_service.is_loaded(),
        whisper_size=whisper_service.get_loaded_model_size() or "?",
        noise_suppression_enabled=noise_enabled,
        noise_suppression_loaded=noise_loaded,
        noise_suppression_error=noise_err,
    )


# ----------------------------------------
# Start / Stop
# ----------------------------------------
class StartRequest(BaseModel):
    device_id: Optional[int] = None
    meeting_id: Optional[int] = None  # Phase 3B+: 상담 연결 녹음


@router.post("/recording/start")
def recording_start(req: StartRequest):
    if live_session.get_active() is not None:
        raise HTTPException(409, "이미 녹음이 진행 중입니다.")

    started_at = datetime.now()

    # ---- meeting_id 가 있으면 meeting row에 지정된 temp_folder 사용 ----
    folder: Optional[Path] = None
    if req.meeting_id is not None:
        try:
            with db_cursor() as cur:
                row = cur.execute(
                    "SELECT id, temp_folder, status FROM meetings WHERE id = ?",
                    (req.meeting_id,),
                ).fetchone()
        except Exception as e:
            raise HTTPException(500, _describe_exc("recording_start:meeting_lookup", e))
        if row is None:
            raise HTTPException(404, f"meeting {req.meeting_id} not found")
        if row["status"] not in ("pending", "recording"):
            raise HTTPException(
                409,
                f"이 상담은 이미 녹음이 끝났습니다 (status={row['status']}).",
            )
        folder = Path(row["temp_folder"])
    else:
        # Phase 2 스타일 단독 테스트
        folder = config.TEMP_RECORDING_DIR / f"session_{started_at.strftime('%Y%m%d_%H%M%S')}"

    folder.mkdir(parents=True, exist_ok=True)
    wav_path = folder / "recording.wav"

    try:
        live_session.start_session(req.device_id, wav_path, meeting_id=req.meeting_id)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(500, _describe_exc("recording_start", e))

    # meeting row 상태 갱신
    if req.meeting_id is not None:
        try:
            with db_cursor() as cur:
                cur.execute(
                    "UPDATE meetings SET status = 'recording', started_at = ? WHERE id = ?",
                    (started_at.isoformat(timespec="seconds"), req.meeting_id),
                )
        except Exception as e:
            # 녹음은 이미 시작됐으므로 DB 업데이트 실패해도 치명적이지 않음 — 로그만
            import traceback as _tb
            print(f"\n[recording_start:status_update] {type(e).__name__}: {e}\n{_tb.format_exc()}", flush=True)

    return {
        "meeting_id": req.meeting_id,
        "wav_path": str(wav_path),
        "started_at": started_at.isoformat(timespec="seconds"),
    }


@router.post("/recording/stop")
def recording_stop():
    """녹음 종료 → 즉시 반환. 마감(MP3·파일 저장) 은 백그라운드 thread.
    클라이언트는 finalize-status 폴링으로 진행 확인.
    """
    if live_session.get_active() is None:
        raise HTTPException(404, "진행 중인 녹음이 없습니다.")
    try:
        result = live_session.stop_session()
    except Exception as e:
        raise HTTPException(500, _describe_exc("recording_stop", e))

    meeting_id = result.get("meeting_id")
    if meeting_id is not None:
        try:
            from app.services import finalize_background
            from app import config
            bg = finalize_background.start_background_finalize(
                meeting_id, result, app_version=config.APP_VERSION,
            )
            result["finalize_background"] = bg
            result["status"] = "finalizing"  # UI 가 폴링 시작
        except Exception as e:
            result["finalize_error"] = _describe_exc("start_background_finalize", e)
            result["status"] = "failed"
    return result


# ----------------------------------------
# v3.5.7: 마감 백그라운드 상태 조회
# ----------------------------------------
@router.get("/meetings/{meeting_id}/finalize-status")
def get_finalize_status(meeting_id: int):
    from app.services import finalize_background
    return finalize_background.get_status(meeting_id)


@router.get("/finalize/active")
def list_active_finalize():
    """헤더 배지용 — 현재 진행 중인 마감 작업들."""
    from app.services import finalize_background
    return {"active": finalize_background.list_active_jobs()}


# ----------------------------------------
# State / Segments
# ----------------------------------------
@router.get("/recording/state")
def recording_state():
    s = live_session.get_active()
    if s is None:
        return {"active": False}
    return s.get_state()


@router.get("/recording/segments")
def recording_segments(since: int = 0):
    """폴링용. WebSocket 이 불안할 때 대체 수단."""
    s = live_session.get_active()
    if s is None:
        return {"active": False, "segments": []}
    return {"active": True, "segments": s.get_segments_since(since)}


# ----------------------------------------
# Speaker 라벨링 (녹음 중)
# ----------------------------------------
class SpeakerUpdateRequest(BaseModel):
    speaker: Optional[str] = None  # 'me' | 'client' | None


@router.post("/recording/segments/{segment_id}/speaker")
def set_recording_segment_speaker(segment_id: int, req: SpeakerUpdateRequest):
    """녹음 중 in-memory 세그먼트의 화자 라벨 변경."""
    s = live_session.get_active()
    if s is None:
        raise HTTPException(404, "진행 중인 녹음이 없습니다.")
    try:
        ok = s.set_segment_speaker(segment_id, req.speaker)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, f"segment {segment_id} not found")
    return {"segment_id": segment_id, "speaker": req.speaker}


# ----------------------------------------
# Phase 8A — 녹음 중 카드 텍스트 편집
# ----------------------------------------
class SegmentTextRequest(BaseModel):
    text: str


@router.patch("/recording/segments/{segment_id}/text")
def edit_recording_segment_text(segment_id: int, req: SegmentTextRequest):
    """
    녹음 중 in-memory 세그먼트의 text 를 사용자 입력으로 교체.
    edited_at 마킹 → finalize 시 DB 에 그대로 저장되고 retranscribe 에서 보존됨.
    """
    s = live_session.get_active()
    if s is None:
        raise HTTPException(404, "진행 중인 녹음이 없습니다.")
    try:
        updated = s.update_segment_text(segment_id, req.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if updated is None:
        raise HTTPException(404, f"segment {segment_id} not found")
    return {
        "segment_id": segment_id,
        "text": updated["text"],
        "edited_at": updated["edited_at"],
    }


# ----------------------------------------
# v3.5.4: 녹음 중 카드 분할
# ----------------------------------------
class SegmentSplitLiveRequest(BaseModel):
    split_at: int


@router.post("/recording/segments/{segment_id}/split")
def split_recording_segment(segment_id: int, req: SegmentSplitLiveRequest):
    """녹음 중 in-memory 카드를 분할 — 한 카드에 두 사람 대화가 같이 있을 때."""
    s = live_session.get_active()
    if s is None:
        raise HTTPException(404, "진행 중인 녹음이 없습니다.")
    try:
        result = s.split_segment(segment_id, req.split_at)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if result is None:
        raise HTTPException(404, f"segment {segment_id} not found")
    return result
