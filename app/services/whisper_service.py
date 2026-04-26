"""
faster-whisper 한국어 전사 서비스.
CPU int8. 모델 사이즈/키워드는 settings 에서 동적 로딩.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from typing import Any, Dict, Optional

import numpy as np

from app import config
from app.services import settings_service

log = logging.getLogger("whisper")


# ========================================
# 반복 환각(repetition hallucination) 감지
# ========================================
# Whisper 가 매장 음악·잡음에 반응해서 의미 없는 같은 단어를 도배하는 실패 모드.
# 예) "작품, 작품, 작품, 작품, 작품, ..." / "음, 음, 음, 음" / "감사합니다 감사합니다 감사합니다"
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")


def _is_repetition_hallucination(text: str) -> bool:
    if not text:
        return False
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return False
    if len(tokens) <= 2:
        # 2 토큰 이하: 같은 토큰만 있으면 hallucination
        return len(set(tokens)) == 1 and len(tokens) >= 2 and len(tokens[0]) <= 4
    counter = Counter(tokens)
    most_common_count = counter.most_common(1)[0][1]
    # 한 토큰이 60% 이상 차지하면 환각으로 판단
    return most_common_count / len(tokens) >= 0.6


# Public alias for use by other modules (예: retranscribe_service)
is_repetition_hallucination = _is_repetition_hallucination


# ========================================
# 멀티 모델 캐시 (live + post-processing 공존)
# ========================================
_live_model = None
_loaded_live_size: Optional[str] = None
_post_models: Dict[str, Any] = {}
_lock = threading.Lock()


def _build_model(size: str):
    """동일 옵션의 WhisperModel 인스턴스를 새로 만든다."""
    from faster_whisper import WhisperModel

    cache = config.MODELS_CACHE_DIR / "whisper"
    cache.mkdir(parents=True, exist_ok=True)
    log.info(f"Loading faster-whisper {size} (cpu int8)...")
    m = WhisperModel(
        size,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        num_workers=1,
        download_root=str(cache),
    )
    log.info(f"faster-whisper {size} loaded")
    return m


def set_model_size(size: str) -> None:
    """런타임에 교체. 다음 get_whisper() 에서 재로딩."""
    global _live_model, _loaded_live_size
    settings_service.set_whisper_model_size(size)
    with _lock:
        _live_model = None
        _loaded_live_size = None


def get_loaded_model_size() -> Optional[str]:
    return _loaded_live_size


def get_whisper():
    """
    실시간 (live) Whisper 모델 싱글톤. settings.whisper.model_size 를 따라감.
    """
    global _live_model, _loaded_live_size
    target_size = settings_service.get_whisper_model_size()

    if _live_model is not None and _loaded_live_size == target_size:
        return _live_model
    with _lock:
        if _live_model is not None and _loaded_live_size == target_size:
            return _live_model
        # post 캐시에 같은 사이즈가 있으면 재사용
        if target_size in _post_models:
            _live_model = _post_models[target_size]
        else:
            _live_model = _build_model(target_size)
        _loaded_live_size = target_size
    return _live_model


def get_post_whisper(size: str):
    """
    후처리(녹음 종료 후 재전사) 전용 모델 캐시.
    live 모델과 다른 사이즈를 동시에 메모리에 올릴 때 사용.
    같은 사이즈가 live 에 이미 로드되어 있으면 그걸 재사용.
    """
    if size in _post_models:
        return _post_models[size]
    with _lock:
        if size in _post_models:
            return _post_models[size]
        if _loaded_live_size == size and _live_model is not None:
            _post_models[size] = _live_model
            return _live_model
        _post_models[size] = _build_model(size)
        return _post_models[size]


def is_loaded() -> bool:
    return _live_model is not None


# ========================================
# 전사
# ========================================
def transcribe_segment(
    audio_float32: np.ndarray,
    sample_rate: int = 16_000,
    prev_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    VAD 로 잘린 한 개의 발화 세그먼트를 전사.
    반환: {"text", "language", "language_prob", "avg_confidence"}
    """
    if audio_float32.size == 0:
        return {"text": "", "language": None, "language_prob": 0.0, "avg_confidence": None}
    if audio_float32.ndim > 1:
        audio_float32 = audio_float32[:, 0]
    audio_float32 = audio_float32.astype(np.float32, copy=False)

    model = get_whisper()
    beam = settings_service.get_whisper_beam_size()
    vocab = settings_service.get_interior_vocab_for_prompt()

    # 도메인 힌트 + 직전 문맥
    prompt = vocab
    if prev_text:
        prompt = f"{vocab} 이전 발화: {prev_text[-200:]}".strip()

    segments, info = model.transcribe(
        audio_float32,
        language="ko",
        beam_size=beam,
        best_of=beam,
        vad_filter=False,         # 이미 VAD 통과했으므로 중복 금지
        initial_prompt=prompt or None,
        condition_on_previous_text=False,
        temperature=[0.0, 0.2, 0.4],
        no_speech_threshold=0.6,
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        word_timestamps=False,
    )

    text_parts = []
    logprobs = []
    for seg in segments:
        t = (seg.text or "").strip()
        if t:
            text_parts.append(t)
        if getattr(seg, "avg_logprob", None) is not None:
            logprobs.append(seg.avg_logprob)

    text = " ".join(text_parts).strip()
    avg_conf = float(sum(logprobs) / len(logprobs)) if logprobs else None

    # 반복 환각이면 빈 문자열로 — LiveSession 측에서 카드 자체를 만들지 않음
    if _is_repetition_hallucination(text):
        log.info(f"hallucination filtered (conf={avg_conf}): {text[:60]}...")
        return {
            "text": "",
            "language": info.language,
            "language_prob": float(info.language_probability or 0.0),
            "avg_confidence": avg_conf,
            "filtered_reason": "repetition_hallucination",
        }

    return {
        "text": text,
        "language": info.language,
        "language_prob": float(info.language_probability or 0.0),
        "avg_confidence": avg_conf,
    }
