"""
v3.5.7 — 녹음 종료 후 마감 작업 (MP3 인코딩·파일 저장) 백그라운드 처리.

배경:
- 1시간 녹음 MP3 인코딩 ~3분, 3시간 ~10분. 노트북에서 더 오래 걸림.
- 현재는 동기 처리라 디자이너가 그 시간 동안 대기.
- 이걸 백그라운드 thread 로 옮겨서 즉시 다음 작업 진행 가능.

흐름:
1. /api/recording/stop → start_background_finalize(meeting_id, result) → 즉시 반환
2. UI 는 헤더 배지에 "🔄 정리 중" 표시
3. /api/meetings/{id}/finalize-status 폴링으로 진행률 확인
4. 완료 시 배지 사라지고 사용자에게 알림
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("finalize_bg")


# 진행 중·완료된 작업들 저장 (in-memory)
# key: meeting_id, value: {state, started_at, completed_at, error, result}
_jobs: Dict[int, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def get_status(meeting_id: int) -> Dict[str, Any]:
    """현재 작업 상태 조회. 없으면 'unknown' 반환."""
    with _jobs_lock:
        job = _jobs.get(meeting_id)
        if job is None:
            return {"meeting_id": meeting_id, "state": "unknown"}
        return dict(job)


def list_active_jobs() -> List[Dict[str, Any]]:
    """현재 'running' 인 작업들 — 헤더 배지용."""
    with _jobs_lock:
        return [dict(j) for j in _jobs.values() if j.get("state") == "running"]


def _cleanup_old_jobs(max_keep: int = 20) -> None:
    """완료된 작업 중 오래된 것 정리 (메모리)."""
    with _jobs_lock:
        if len(_jobs) <= max_keep:
            return
        # 완료된 것만 가장 오래된 것부터 제거
        completed = [
            (mid, j) for mid, j in _jobs.items()
            if j.get("state") in ("completed", "failed")
        ]
        completed.sort(key=lambda x: x[1].get("completed_at") or 0)
        excess = len(_jobs) - max_keep
        for mid, _ in completed[:excess]:
            _jobs.pop(mid, None)


def start_background_finalize(
    meeting_id: int,
    final_result: Dict[str, Any],
    app_version: str = "unknown",
) -> Dict[str, Any]:
    """
    백그라운드 thread 에서 meeting_finalizer.finalize_meeting() 실행.
    즉시 시작 정보 반환.
    """
    # 이미 같은 meeting 에 대한 작업이 running 이면 거부
    with _jobs_lock:
        existing = _jobs.get(meeting_id)
        if existing and existing.get("state") == "running":
            return {
                "meeting_id": meeting_id,
                "state": "already_running",
                "started_at": existing.get("started_at"),
            }
        _jobs[meeting_id] = {
            "meeting_id": meeting_id,
            "state": "running",
            "started_at": time.time(),
            "completed_at": None,
            "error": None,
            "result": None,
            "stage": "starting",
        }

    def _worker():
        from app.services import meeting_finalizer
        try:
            log.info(f"[finalize_bg] meeting {meeting_id} 시작")
            _update_job(meeting_id, stage="encoding_mp3")
            finalized = meeting_finalizer.finalize_meeting(
                meeting_id, final_result, app_version=app_version,
            )
            _update_job(
                meeting_id, state="completed",
                completed_at=time.time(),
                result=finalized,
                stage="done",
            )
            log.info(f"[finalize_bg] meeting {meeting_id} 완료")
        except Exception as e:
            import traceback as _tb
            err_msg = f"{type(e).__name__}: {str(e)[:300]}"
            log.error(f"[finalize_bg] meeting {meeting_id} 실패: {err_msg}\n{_tb.format_exc()}")
            _update_job(
                meeting_id, state="failed",
                completed_at=time.time(),
                error=err_msg,
                stage="error",
            )
        finally:
            _cleanup_old_jobs()

    t = threading.Thread(target=_worker, daemon=True, name=f"finalize-{meeting_id}")
    t.start()
    return {
        "meeting_id": meeting_id,
        "state": "running",
        "started_at": _jobs[meeting_id]["started_at"],
    }


def _update_job(meeting_id: int, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(meeting_id)
        if job is not None:
            job.update(fields)
