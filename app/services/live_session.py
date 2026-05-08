"""
실시간 녹음·전사 세션 (Phase 2).

파이프라인:
  [mic]-callback-> audio_q
                      │
                  processor thread  ── write WAV  (동시)
                      │            └─ StreamingVAD
                      ▼
                  speech_q
                      │
                  whisper thread   ── transcribe
                      ▼
                  segments[]  (+WebSocket broadcast)
"""
from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import soundfile as sf

from app.services.audio_recorder import (
    BLOCKSIZE, CHANNELS, DTYPE, QUEUE_MAX, Recorder, SAMPLE_RATE,
)
from app.services import noise_suppression_service, settings_service
from app.services.vad_service import StreamingVAD
from app.services.whisper_service import get_whisper, transcribe_segment

log = logging.getLogger("live_session")


class LiveSession:
    """녹음 1건의 전체 파이프라인."""

    def __init__(
        self,
        device_id: Optional[int],
        wav_path: Path,
        meeting_id: Optional[int] = None,
    ):
        self.device_id = device_id
        self.wav_path = wav_path
        self.meeting_id = meeting_id  # Phase 3B+: 연결된 DB meeting row
        self.started_at: datetime = datetime.now()
        self.stopped_at: Optional[datetime] = None

        # Phase 5B: 노이즈 억제 사용 여부 (세션 시작 시점에 캡처)
        self.noise_suppression_enabled = (
            settings_service.get_noise_suppression_enabled()
        )
        # 버퍼드 디노이저 (세션당 1개, 500ms 청크 단위 처리)
        self._denoiser: Optional[noise_suppression_service.BufferedDenoiser] = None
        if self.noise_suppression_enabled:
            self._denoiser = noise_suppression_service.BufferedDenoiser(
                sample_rate=SAMPLE_RATE
            )

        # 큐
        self._audio_q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=QUEUE_MAX)
        self._speech_q: "queue.Queue[Optional[Dict]]" = queue.Queue()

        # 완결된 전사 세그먼트 (id 순)
        self._segments: List[Dict[str, Any]] = []
        self._segments_lock = threading.Lock()
        self._next_id = 1
        self._last_text_for_prompt: Optional[str] = None

        # 스레드/제어
        self._stop_evt = threading.Event()
        self._recorder = Recorder(device_id, self._audio_q)
        self._sf: Optional[sf.SoundFile] = None
        self._vad: Optional[StreamingVAD] = None
        self._proc_thread: Optional[threading.Thread] = None
        self._whisper_thread: Optional[threading.Thread] = None

        # 메트릭
        self._metrics = {
            "rms_db": -120.0,
            "frames_written": 0,
        }
        self._metrics_lock = threading.Lock()

    # ----------------------------------------
    # 외부 제어
    # ----------------------------------------
    def start(self) -> None:
        self.wav_path.parent.mkdir(parents=True, exist_ok=True)
        self._sf = sf.SoundFile(
            str(self.wav_path), mode="w",
            samplerate=SAMPLE_RATE, channels=CHANNELS, subtype="PCM_16",
        )
        self._vad = StreamingVAD(sample_rate=SAMPLE_RATE)

        self._proc_thread = threading.Thread(
            target=self._processor_loop, daemon=True, name="audio-processor",
        )
        self._whisper_thread = threading.Thread(
            target=self._whisper_loop, daemon=True, name="whisper-worker",
        )
        self._proc_thread.start()
        self._whisper_thread.start()

        # 마지막에 마이크를 연다 (writer 준비 후)
        self._recorder.start()

    def stop(self) -> None:
        self.stopped_at = datetime.now()

        # 1) 마이크 중단 (audio_q 에 더 이상 공급 없음)
        self._recorder.stop()

        # 2) 오디오 processor 종료 대기 (큐 드레인)
        self._stop_evt.set()
        if self._proc_thread is not None:
            self._proc_thread.join(timeout=10.0)

        # 3) VAD 가 붙들고 있던 진행중 발화를 emit
        if self._vad is not None:
            for s in self._vad.finalize():
                self._speech_q.put(s)

        # 4) whisper 워커에 종료 센티넬 + 남은 세그먼트 처리 대기
        self._speech_q.put(None)
        if self._whisper_thread is not None:
            self._whisper_thread.join(timeout=120.0)

        # 5) WAV close
        if self._sf is not None:
            try:
                self._sf.flush()
                self._sf.close()
            except Exception:
                pass
            self._sf = None

    # ----------------------------------------
    # 워커 루프
    # ----------------------------------------
    def _process_block(self, block: np.ndarray) -> None:
        """단일 (이미 enhance 된) 블록을 WAV 쓰기 + 메트릭 + VAD 입력."""
        # (1) WAV 쓰기
        try:
            self._sf.write(block)
        except Exception as e:
            log.error(f"WAV write error: {e}")

        # (2) 메트릭 (레벨) 계산
        arr = block.astype(np.float32) / 32768.0
        if arr.size:
            rms = float(np.sqrt(np.mean(arr * arr)))
            db = 20.0 * float(np.log10(max(rms, 1e-7)))
            with self._metrics_lock:
                self._metrics["rms_db"] = db
                self._metrics["frames_written"] += int(block.shape[0])

        # (3) VAD 입력
        try:
            completed = self._vad.feed(block)
            for seg in completed:
                self._speech_q.put(seg)
        except Exception as e:
            log.error(f"VAD feed error: {type(e).__name__}: {e}")

    def _processor_loop(self) -> None:
        """
        mic → (옵션) 노이즈제거 버퍼링(500ms 청크) → WAV + VAD.
        노이즈 제거 OFF: 100ms 블록을 즉시 처리.
        노이즈 제거 ON: 500ms 모일 때마다 한 번에 enhance → 처리.
        """
        assert self._sf is not None and self._vad is not None
        while not (self._stop_evt.is_set() and self._audio_q.empty()):
            try:
                block = self._audio_q.get(timeout=0.2)
            except queue.Empty:
                continue

            if self._denoiser is not None:
                # 노이즈 제거 ON — 500ms 청크가 모이면 한 번에 처리
                try:
                    enhanced_chunks = self._denoiser.feed(block)
                except Exception as e:
                    log.warning(f"denoiser feed error (fallback to raw): {type(e).__name__}: {e}")
                    self._process_block(block)
                    continue
                for chunk in enhanced_chunks:
                    self._process_block(chunk)
            else:
                # 노이즈 제거 OFF — 즉시 처리
                self._process_block(block)

        # 루프 종료 시 디노이저 잔여 버퍼 flush
        if self._denoiser is not None:
            try:
                tail = self._denoiser.flush()
                if tail is not None and tail.size > 0:
                    self._process_block(tail)
            except Exception as e:
                log.warning(f"denoiser flush error: {type(e).__name__}: {e}")

    def _whisper_loop(self) -> None:
        """speech_q → Whisper 전사 → _segments 에 누적."""
        # 모델 예열 (한 번)
        try:
            get_whisper()
        except Exception as e:
            log.error(f"Whisper load failed: {type(e).__name__}: {e}")
            # 이후에도 계속 poll 하다 실패 — 최소한 큐는 비움
            while True:
                item = self._speech_q.get()
                if item is None:
                    return

        while True:
            seg = self._speech_q.get()
            if seg is None:  # stop sentinel
                return
            try:
                vad_start_ms = int(seg["start_sample"] * 1000 / SAMPLE_RATE)
                vad_end_ms = int(seg["end_sample"] * 1000 / SAMPLE_RATE)
                result = transcribe_segment(
                    seg["audio"],
                    sample_rate=SAMPLE_RATE,
                    prev_text=self._last_text_for_prompt,
                )
                text = (result.get("text") or "").strip()
                if not text:
                    continue
                avg_conf = result.get("avg_confidence")

                # v3.5.4: sub_segments 가 있으면 마침표 단위로 분할해 여러 카드 생성
                # 없거나 1개면 기존처럼 1개 카드
                sub_segs = result.get("sub_segments") or []
                if len(sub_segs) <= 1:
                    cards = [{
                        "start_ms": vad_start_ms,
                        "end_ms": vad_end_ms,
                        "text": text,
                    }]
                else:
                    # whisper 의 start/end (초) 는 audio 청크 시작 기준 → VAD start 더해서 절대 시간으로
                    cards = []
                    for ss in sub_segs:
                        s_ms = vad_start_ms + int(ss["start"] * 1000)
                        e_ms = vad_start_ms + int(ss["end"] * 1000)
                        # VAD 구간 밖으로 나가지 않도록 clamp
                        s_ms = max(vad_start_ms, min(s_ms, vad_end_ms))
                        e_ms = max(s_ms, min(e_ms, vad_end_ms))
                        cards.append({
                            "start_ms": s_ms,
                            "end_ms": e_ms,
                            "text": ss["text"],
                        })

                now_iso = datetime.now().isoformat(timespec="seconds")
                with self._segments_lock:
                    for c in cards:
                        entry = {
                            "id": self._next_id,
                            "start_ms": c["start_ms"],
                            "end_ms": c["end_ms"],
                            "duration_ms": max(0, c["end_ms"] - c["start_ms"]),
                            "text": c["text"],
                            "confidence": avg_conf,
                            "speaker": None,
                            "edited_at": None,
                            "created_at": now_iso,
                        }
                        self._segments.append(entry)
                        self._next_id += 1
                self._last_text_for_prompt = text
            except Exception as e:
                log.error(f"Whisper transcribe error: {type(e).__name__}: {e}")

    # ----------------------------------------
    # 조회
    # ----------------------------------------
    def get_state(self) -> Dict[str, Any]:
        elapsed = (datetime.now() - self.started_at).total_seconds()
        with self._metrics_lock:
            m = dict(self._metrics)
        with self._segments_lock:
            segs = list(self._segments)
        return {
            "active": True,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "elapsed_sec": round(elapsed, 2),
            "rms_db": round(m["rms_db"], 1),
            "frames_written": m["frames_written"],
            "audio_queue_depth": self._audio_q.qsize(),
            "speech_queue_depth": self._speech_q.qsize(),
            "dropped_blocks": self._recorder.dropped,
            "wav_path": str(self.wav_path),
            "segments_count": len(segs),
            "segments": segs,
        }

    def get_segments_since(self, last_id: int) -> List[Dict[str, Any]]:
        with self._segments_lock:
            return [s for s in self._segments if s["id"] > last_id]

    def set_segment_speaker(self, segment_id: int, speaker: Optional[str]) -> bool:
        """
        녹음 중 메모리 내 세그먼트의 speaker 를 업데이트.
        True=성공, False=세그먼트 없음.
        """
        if speaker not in (None, "me", "client"):
            raise ValueError(f"invalid speaker: {speaker}")
        with self._segments_lock:
            for s in self._segments:
                if s["id"] == segment_id:
                    s["speaker"] = speaker
                    return True
        return False

    def update_segment_text(self, segment_id: int, text: str) -> Optional[Dict[str, Any]]:
        """
        Phase 8A — 녹음 중 메모리 내 세그먼트의 text 를 사용자 편집으로 교체.
        edited_at 타임스탬프를 찍어 두면 finalize 시 그대로 DB 저장되고
        나중에 retranscribe 가 이 카드를 보존(시간 겹침 시 새 카드 폐기) 한다.
        반환: 수정된 segment dict 사본, 못 찾으면 None.
        """
        new_text = (text or "").strip()
        if not new_text:
            raise ValueError("빈 텍스트로 교체할 수 없습니다.")
        with self._segments_lock:
            for s in self._segments:
                if s["id"] == segment_id:
                    s["text"] = new_text
                    s["edited_at"] = datetime.now().isoformat(timespec="seconds")
                    return dict(s)
        return None

    def split_segment(self, segment_id: int, split_at: int) -> Optional[Dict[str, Any]]:
        """v3.5.4 — 녹음 중 in-memory 카드를 둘로 분할.
        텍스트는 split_at 위치에서 자르고, 시간(start_ms ~ end_ms) 은 텍스트 길이 비례.
        반환: {left, right} 두 카드 dict, 못 찾으면 None.
        """
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self._segments_lock:
            for i, s in enumerate(self._segments):
                if s["id"] != segment_id:
                    continue
                text = s["text"] or ""
                n = len(text)
                at = max(1, min(int(split_at), n - 1))
                left_t = text[:at].strip()
                right_t = text[at:].strip()
                if not left_t or not right_t:
                    raise ValueError("분할 위치가 텍스트 끝에 너무 가깝습니다.")
                start_ms = int(s["start_ms"])
                end_ms = int(s["end_ms"])
                ratio = at / n
                mid_ms = start_ms + int((end_ms - start_ms) * ratio)
                mid_ms = max(start_ms + 100, min(mid_ms, end_ms - 100))
                # 원본을 left 로 변경
                s["text"] = left_t
                s["end_ms"] = mid_ms
                s["duration_ms"] = max(0, mid_ms - start_ms)
                s["edited_at"] = now_iso
                # 새 right 카드 생성 (id 새로 할당)
                right = {
                    "id": self._next_id,
                    "start_ms": mid_ms,
                    "end_ms": end_ms,
                    "duration_ms": max(0, end_ms - mid_ms),
                    "text": right_t,
                    "confidence": s.get("confidence"),
                    "speaker": s.get("speaker"),
                    "edited_at": now_iso,
                    "created_at": s.get("created_at") or now_iso,
                }
                self._next_id += 1
                # 원본 바로 다음 위치에 right 삽입 (start_ms 정렬 유지)
                self._segments.insert(i + 1, right)
                return {"left": dict(s), "right": dict(right)}
        return None

    def final_result(self) -> Dict[str, Any]:
        duration = (
            (self.stopped_at - self.started_at).total_seconds()
            if self.stopped_at is not None
            else 0.0
        )
        with self._segments_lock:
            segs = list(self._segments)
        return {
            "meeting_id": self.meeting_id,
            "wav_path": str(self.wav_path),
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "ended_at": self.stopped_at.isoformat(timespec="seconds") if self.stopped_at else None,
            "duration_sec": round(duration, 2),
            "size_bytes": self.wav_path.stat().st_size if self.wav_path.exists() else 0,
            "segments_count": len(segs),
            "segments": segs,
            "dropped_blocks": self._recorder.dropped,
        }


# ========================================
# Singleton (1인 사용)
# ========================================
_lock = threading.Lock()
_active: Optional[LiveSession] = None


def get_active() -> Optional[LiveSession]:
    with _lock:
        return _active


def start_session(
    device_id: Optional[int],
    wav_path: Path,
    meeting_id: Optional[int] = None,
) -> LiveSession:
    global _active
    with _lock:
        if _active is not None:
            raise RuntimeError("already_recording")
        s = LiveSession(device_id, wav_path, meeting_id=meeting_id)
        s.start()
        _active = s
        return s


def stop_session() -> Dict[str, Any]:
    global _active
    with _lock:
        if _active is None:
            raise RuntimeError("no_active_session")
        s = _active
        _active = None
    # stop 은 I/O + join → lock 밖에서
    s.stop()
    result = s.final_result()
    # 세션 객체 해제 + GC — 녹음 버퍼·numpy 배열 즉시 회수
    del s
    import gc
    gc.collect()
    return result
