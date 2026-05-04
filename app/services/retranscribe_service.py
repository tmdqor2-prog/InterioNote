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

    # 기존 라벨 확보 (이관용) + 되돌리기 스냅샷 저장
    old_segments = meeting_finalizer.load_segments_from_db(meeting_id)
    try:
        snapshot_count = meeting_finalizer.save_segments_snapshot(meeting_id, label="pre_retranscribe")
        print(f"[retranscribe] undo snapshot saved: {snapshot_count} segments", flush=True)
    except Exception as e:
        # 스냅샷 실패해도 재전사 자체는 진행 (단, 되돌리기 불가)
        log.warning(f"snapshot save failed: {type(e).__name__}: {e}")

    # 도메인 힌트 + 파라미터
    vocab = settings_service.get_interior_vocab_for_prompt()
    beam = settings_service.get_whisper_beam_size()
    vad_threshold = settings_service.get_vad_threshold()

    # 전체 WAV 를 한 번에 전사 — faster-whisper 의 내장 VAD 사용
    # Phase 8A 수정: word_timestamps=True 로 단어별 시간 정보 받음 → 옛 카드 시간 범위에 재분배
    print(f"[retranscribe] step 2/4: starting transcribe (beam={beam}, vad_threshold={vad_threshold}, word_ts=True)...", flush=True)
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
        word_timestamps=True,
    )
    print(f"[retranscribe] step 2/4: transcribe handle obtained in {time.time() - t_tr_start:.1f}s, iterating segments...", flush=True)

    # medium 의 raw segments + words 모두 수집
    raw_segments: List[Dict[str, Any]] = []  # whisper 가 만든 sentence-level 묶음
    all_words: List[Dict[str, Any]] = []     # 단어별 timestamp (재분배용)
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
        raw_segments.append({
            "start_ms": int(seg.start * 1000),
            "end_ms": int(seg.end * 1000),
            "text": text,
            "confidence": conf,
            "speaker": None,
        })
        # 단어별 timestamp 수집
        words = getattr(seg, "words", None) or []
        for w in words:
            wt = (getattr(w, "word", "") or "").strip()
            if not wt:
                continue
            all_words.append({
                "start_ms": int((w.start or 0) * 1000),
                "end_ms": int((w.end or 0) * 1000),
                "text": wt,
            })

    # ----- Phase 8A: 옛 카드 구조 보존 + 사용자 편집 보호 -----
    # 옛 카드들의 시간 범위는 silero-vad 기반으로 발화 단위로 잘 쪼개져 있음.
    # medium 의 word-level timestamp 를 옛 카드 범위에 재분배하면
    #  - 카드 분할(=시각적 단위) 그대로 유지
    #  - 텍스트는 더 정확한 medium 결과로 갱신
    #  - 화자 라벨은 자동으로 위치 그대로 따라감
    #  - edited_at 카드는 텍스트 교체 안 함 (사용자 편집 보호)
    final_segments: List[Dict[str, Any]] = []
    edited_preserved = 0
    refilled_count = 0
    kept_old_count = 0      # medium 이 못 잡았지만 옛 텍스트가 진짜 같아 그대로 보존
    dropped_hallucination = 0  # medium 이 못 잡은 데다 옛 텍스트도 환각 → 폐기
    labels_transferred = 0  # 옛 라벨이 그대로 살아있으니 == 라벨이 있는 옛 카드 수

    # 단어 매칭에 약간의 시간 여유 — 발화 경계에서 medium VAD 가 silero-vad 와
    # 미묘하게 다른 위치를 잡는 것을 흡수. 특히 마지막 카드의 끝부분에서 효과.
    BOUNDARY_TOLERANCE_MS = 300

    if old_segments:
        for old in old_segments:
            old_speaker = old.get("speaker")
            old_text = (old.get("text") or "").strip()

            if old.get("edited_at"):
                # 사용자 편집 카드: 텍스트 그대로 보존
                final_segments.append({
                    "start_ms": int(old["start_ms"]),
                    "end_ms": int(old["end_ms"]),
                    "text": old_text,
                    "speaker": old_speaker,
                    "confidence": old.get("confidence"),
                    "edited_at": old.get("edited_at"),
                })
                edited_preserved += 1
                if old_speaker:
                    labels_transferred += 1
                continue

            # 비편집 카드: 이 시간 범위 + 경계 여유에 들어가는 medium 단어 수집
            s, e = int(old["start_ms"]), int(old["end_ms"])
            s_wide = s - BOUNDARY_TOLERANCE_MS
            e_wide = e + BOUNDARY_TOLERANCE_MS
            contained_words = []
            for w in all_words:
                w_center = (w["start_ms"] + w["end_ms"]) / 2
                if s_wide <= w_center <= e_wide:
                    contained_words.append(w["text"])
            new_text = " ".join(contained_words).strip()

            if new_text and not is_repetition_hallucination(new_text):
                # medium 결과가 있고 환각도 아님 → 정상 갱신
                final_segments.append({
                    "start_ms": s,
                    "end_ms": e,
                    "text": new_text,
                    "speaker": old_speaker,
                    "confidence": None,
                    "edited_at": None,
                })
                refilled_count += 1
                if old_speaker:
                    labels_transferred += 1
                continue

            # medium 이 못 잡았거나 환각만 잡음 → 옛 텍스트 평가
            if old_text and not is_repetition_hallucination(old_text):
                # 옛 텍스트가 진짜 같으면 보존 (사용자 컨텐츠 손실 방지)
                # 특히 마지막 카드는 녹음 끝 직전 짧게 잘려 medium 이 놓치기 쉬움.
                final_segments.append({
                    "start_ms": s,
                    "end_ms": e,
                    "text": old_text,
                    "speaker": old_speaker,
                    "confidence": old.get("confidence"),
                    "edited_at": None,
                })
                kept_old_count += 1
                if old_speaker:
                    labels_transferred += 1
            else:
                # 옛것도 환각 → 진짜로 버림
                dropped_hallucination += 1
    else:
        # 옛 카드가 전혀 없는 경우 (드물지만 가능): medium 의 raw segment 그대로 사용
        for ns in raw_segments:
            ns["edited_at"] = None
            final_segments.append(ns)

    final_segments.sort(key=lambda s: (int(s["start_ms"]), 0))

    # v2.5.1 M: 한국어 punctuation 정리 (사용자 편집 카드는 건드리지 않음)
    try:
        from app.services import text_polish
        polished_count = text_polish.polish_segments_in_place(
            final_segments, only_unedited=True
        )
        if polished_count:
            log.info(f"polished {polished_count} segments with korean punctuation")
    except Exception as e:
        log.warning(f"text_polish 실패 (skip): {type(e).__name__}: {e}")

    # DB: 기존 segments 삭제 + 최종 세트 삽입
    try:
        with db_cursor() as cur:
            cur.execute(
                "DELETE FROM transcript_segments WHERE meeting_id = ?",
                (meeting_id,),
            )
            if final_segments:
                cur.executemany(
                    """
                    INSERT INTO transcript_segments
                        (meeting_id, start_ms, end_ms, text, speaker, confidence, edited_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            meeting_id,
                            int(s["start_ms"]),
                            int(s["end_ms"]),
                            s["text"],
                            s.get("speaker"),
                            s.get("confidence"),
                            s.get("edited_at"),
                        )
                        for s in final_segments
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
        "raw_medium_segments_count": len(raw_segments),
        "edited_preserved_count": edited_preserved,
        "refilled_count": refilled_count,
        "kept_old_count": kept_old_count,                   # medium 이 못 잡아 옛 텍스트 보존
        "dropped_hallucination_count": dropped_hallucination,
        "final_segments_count": len(final_segments),
        "labels_transferred": labels_transferred,
        "hallucinations_filtered": hallucinations_filtered,
        "elapsed_sec": round(elapsed, 2),
        "md_warning": md_warning,
    }
