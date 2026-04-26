"""
녹음 종료 후 더 정확한 모델로 재전사하는 Two-pass 후처리 (Phase 5C).

흐름:
1. 상담 폴더의 '녹음원본.wav' 로드
2. faster-whisper 의 내장 VAD 로 분할 + 지정 모델로 전사
3. 환각 필터 적용
4. 기존 segments 의 화자 라벨을 시간 겹침으로 새 segments 에 이관
5. transcript_segments 교체 + 대화전문.md 재생성
"""
from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db import db_cursor
from app.services import (
    meeting_finalizer,
    settings_service,
    whisper_service,
)
from app.services.whisper_service import is_repetition_hallucination

log = logging.getLogger("retranscribe")


def _load_meeting_and_client(meeting_id: int) -> Optional[Dict[str, Any]]:
    return meeting_finalizer._load_meeting_and_client(meeting_id)


def _transfer_speaker_labels(
    new_segments: List[Dict[str, Any]],
    old_segments: List[Dict[str, Any]],
) -> int:
    """
    기존 segments 의 speaker 라벨을 새 segments 에 시간 겹침으로 이관.
    각 새 segment 의 중심 시각이 어느 old segment 안에 들어가면 라벨 복사.
    반환: 이관된 라벨 수.
    """
    if not old_segments:
        return 0
    transferred = 0
    for new_seg in new_segments:
        center = (int(new_seg["start_ms"]) + int(new_seg["end_ms"])) / 2
        for old in old_segments:
            sp = old.get("speaker")
            if not sp:
                continue
            if int(old["start_ms"]) <= center <= int(old["end_ms"]):
                new_seg["speaker"] = sp
                transferred += 1
                break
    return transferred


def retranscribe_meeting(
    meeting_id: int,
    *,
    model_size: str = "medium",
) -> Dict[str, Any]:
    """
    meeting_id 의 녹음원본.wav 를 더 큰 모델로 재전사.
    transcript_segments 를 교체하고 대화전문.md 재생성.
    """
    started = time.time()

    meeting = _load_meeting_and_client(meeting_id)
    if meeting is None:
        raise ValueError(f"meeting {meeting_id} not found")

    if not meeting.get("meeting_folder"):
        raise ValueError("상담 폴더가 지정되지 않은 상담입니다 (Phase 3C 마감 필요).")

    meeting_folder = Path(meeting["meeting_folder"])
    if not meeting_folder.exists():
        raise FileNotFoundError(f"상담 폴더를 찾을 수 없습니다: {meeting_folder}")

    wav_path = meeting_folder / "녹음원본.wav"
    if not wav_path.exists():
        raise FileNotFoundError(
            f"녹음원본.wav 가 없습니다: {wav_path}\n"
            "이전에 녹음된 상담은 WAV 가 보존되지 않았을 수 있습니다. "
            "다음 녹음부터 자동 보존됩니다."
        )

    # 모델 로드 (필요 시 다운로드)
    print(f"[retranscribe] meeting={meeting_id} model={model_size} wav={wav_path}", flush=True)
    log.info(f"retranscribe meeting={meeting_id} model={model_size}")
    print(f"[retranscribe] step 1/4: loading model {model_size}...", flush=True)
    t_model_start = time.time()
    model = whisper_service.get_post_whisper(model_size)
    print(f"[retranscribe] step 1/4 done in {time.time() - t_model_start:.1f}s", flush=True)

    # 기존 라벨 확보 (이관용)
    old_segments = meeting_finalizer.load_segments_from_db(meeting_id)

    # 도메인 힌트 + 파라미터
    vocab = settings_service.get_interior_vocab_for_prompt()
    beam = settings_service.get_whisper_beam_size()
    vad_threshold = settings_service.get_vad_threshold()

    # 전체 WAV 를 한 번에 전사 — faster-whisper 의 내장 VAD 사용
    print(f"[retranscribe] step 2/4: starting transcribe (beam={beam}, vad_threshold={vad_threshold})...", flush=True)
    t_tr_start = time.time()
    seg_iter, info = model.transcribe(
        str(wav_path),
        language="ko",
        beam_size=beam,
        best_of=beam,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            threshold=vad_threshold,
        ),
        initial_prompt=vocab or None,
        condition_on_previous_text=False,
        temperature=[0.0, 0.2, 0.4],
        no_speech_threshold=0.6,
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        word_timestamps=False,
    )
    print(f"[retranscribe] step 2/4: transcribe handle obtained in {time.time() - t_tr_start:.1f}s, iterating segments...", flush=True)

    new_segments: List[Dict[str, Any]] = []
    hallucinations_filtered = 0
    seg_count = 0
    for seg in seg_iter:
        seg_count += 1
        if seg_count <= 20 or seg_count % 10 == 0:
            print(f"[retranscribe]   segment {seg_count}: [{seg.start:.1f}-{seg.end:.1f}] {(seg.text or '')[:40]}", flush=True)
        text = (seg.text or "").strip()
        if not text:
            continue
        if is_repetition_hallucination(text):
            hallucinations_filtered += 1
            log.info(f"hallucination filtered: {text[:60]}")
            continue
        conf = None
        if getattr(seg, "avg_logprob", None) is not None:
            conf = float(seg.avg_logprob)
        new_segments.append({
            "start_ms": int(seg.start * 1000),
            "end_ms": int(seg.end * 1000),
            "text": text,
            "confidence": conf,
            "speaker": None,
        })

    # 라벨 이관
    labels_transferred = _transfer_speaker_labels(new_segments, old_segments)

    # DB: 기존 segments 삭제 + 새 segments 삽입
    try:
        with db_cursor() as cur:
            cur.execute(
                "DELETE FROM transcript_segments WHERE meeting_id = ?",
                (meeting_id,),
            )
            if new_segments:
                cur.executemany(
                    """
                    INSERT INTO transcript_segments
                        (meeting_id, start_ms, end_ms, text, speaker, confidence)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            meeting_id,
                            int(s["start_ms"]),
                            int(s["end_ms"]),
                            s["text"],
                            s.get("speaker"),
                            s.get("confidence"),
                        )
                        for s in new_segments
                    ],
                )
    except Exception as e:
        log.error(f"DB replace failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        raise

    # 대화전문.md 재생성
    md_warning = None
    try:
        meeting_finalizer.regenerate_transcript_md(meeting_id)
    except Exception as e:
        md_warning = f"{type(e).__name__}: {e}"
        log.error(f"regenerate_transcript_md failed: {md_warning}")

    elapsed = time.time() - started
    return {
        "meeting_id": meeting_id,
        "model": model_size,
        "old_segments_count": len(old_segments),
        "new_segments_count": len(new_segments),
        "labels_transferred": labels_transferred,
        "hallucinations_filtered": hallucinations_filtered,
        "elapsed_sec": round(elapsed, 2),
        "md_warning": md_warning,
    }
