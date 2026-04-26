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
    if live_session.get_active() is None:
        raise HTTPException(404, "진행 중인 녹음이 없습니다.")
    try:
        result = live_session.stop_session()
    except Exception as e:
        raise HTTPException(500, _describe_exc("recording_stop", e))

    # Phase 3C: meeting 에 연결된 녹음이면 최종 폴더로 이동 + MP3 + MD + JSON
    meeting_id = result.get("meeting_id")
    if meeting_id is not None:
        try:
            finalized = meeting_finalizer.finalize_meeting(
                meeting_id,
                result,
                app_version="2.0.0",
            )
            # 요약 필드를 합쳐서 UI 로 반환
            result["finalized"] = finalized
            result["meeting_folder"] = finalized["meeting_folder"]
            result["mp3_path"] = finalized["mp3_path"]
            result["mp3_size_bytes"] = finalized.get("mp3_size_bytes")
            result["markdown_path"] = finalized["markdown_path"]
            result["info_json_path"] = finalized["info_json_path"]
            result["status"] = finalized["status"]
            # DB 에서 다시 불러온 세그먼트 (DB id 포함) 로 교체
            if finalized.get("segments") is not None:
                result["segments"] = finalized["segments"]
                result["segments_count"] = finalized.get("segments_count", len(finalized["segments"]))
        except Exception as e:
            # 마감 실패는 녹음 자체는 성공했으므로 500 이 아니라 부분 성공 응답
            result["finalize_error"] = _describe_exc("finalize_meeting", e)
            result["status"] = "failed"
    return result


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
