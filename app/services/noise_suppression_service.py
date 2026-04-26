"""
silero-denoise 기반 음성 향상 (노이즈 억제) — Phase 5B.

⚠️ silero-denoise 는 ~500ms 정도의 컨텍스트가 필요하다. 100ms 짜리 작은
블록을 그대로 넣으면 거의 무음을 출력해 버린다.
따라서 BufferedDenoiser 가 입력을 누적했다가 chunk_samples (기본 8000=500ms)
가 모이면 한꺼번에 처리한다.

흐름 (LiveSession 측):
  audio_q  →  BufferedDenoiser.feed(block) → list[enhanced_chunks]
                                          → 각 chunk 를 WAV 쓰기 + VAD 입력
세션 종료 시 BufferedDenoiser.flush() 로 잔여 버퍼 처리.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional

import numpy as np

from app import config

log = logging.getLogger("noise")


# ========================================
# 모델 싱글톤
# ========================================
_model = None
_resampler_32_to_16 = None   # torchaudio Resample 32kHz → 16kHz
_lock = threading.Lock()
_load_error: Optional[str] = None
_model_name = "small_slow"

_TORCH_HUB_DIR = config.MODELS_CACHE_DIR / "torch_hub"

# silero-denoise 가 출력하는 샘플레이트 (입력 16kHz 의 약 2배)
_MODEL_OUTPUT_SR = 32_000


def is_loaded() -> bool:
    return _model is not None


def get_load_error() -> Optional[str]:
    return _load_error


def warmup() -> None:
    _ensure_loaded()


def _ensure_loaded() -> None:
    """첫 호출 시 모델 로드 (~52MB GitHub 다운로드 — 캐시되면 재사용)."""
    global _model, _resampler_32_to_16, _load_error
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        try:
            import torch
            import torchaudio.transforms as T

            torch.set_num_threads(1)
            _TORCH_HUB_DIR.mkdir(parents=True, exist_ok=True)
            os.environ["TORCH_HOME"] = str(_TORCH_HUB_DIR)
            torch.hub.set_dir(str(_TORCH_HUB_DIR))

            log.info(f"Loading silero-denoise ({_model_name})...")
            model, _samples, _utils = torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_denoise",
                name=_model_name,
                device="cpu",
                trust_repo=True,
            )
            model.eval()
            _model = model
            # 출력 32kHz → 16kHz 다운샘플러
            _resampler_32_to_16 = T.Resample(
                orig_freq=_MODEL_OUTPUT_SR, new_freq=16_000
            )
            _load_error = None
            log.info("silero-denoise loaded")
        except Exception as e:
            _load_error = f"{type(e).__name__}: {e}"
            log.error(f"silero-denoise load failed: {_load_error}")
            raise


# ========================================
# 단일 chunk enhance (내부)
# ========================================
def _enhance_chunk_int16(pcm_int16_16k: np.ndarray) -> np.ndarray:
    """
    16kHz int16 mono chunk (≥500ms 권장) → silero(out 32kHz) → 16kHz 다운샘플
    → 입력과 동일 길이 int16 반환. 실패 시 원본 통과.
    """
    if pcm_int16_16k is None or pcm_int16_16k.size == 0:
        return pcm_int16_16k

    try:
        _ensure_loaded()
    except Exception:
        return pcm_int16_16k

    try:
        import torch

        if pcm_int16_16k.ndim > 1:
            mono = pcm_int16_16k[:, 0]
        else:
            mono = pcm_int16_16k

        n_in = mono.shape[0]

        # int16 → float32 [-1, 1)
        f32 = mono.astype(np.float32) / 32768.0
        x = torch.from_numpy(f32).unsqueeze(0)  # (1, N) at 16kHz

        # 모델 추론 — 출력은 32kHz @ ~2N 샘플 (3D 텐서 (1,1,M))
        with torch.no_grad():
            y = _model(x)

        if isinstance(y, (tuple, list)):
            y = y[0]
        # (1, 1, M) → (1, M)
        if y.dim() == 3:
            y = y.squeeze(1)
        elif y.dim() == 1:
            y = y.unsqueeze(0)
        # y shape == (1, M) at 32kHz

        # 32kHz → 16kHz 다운샘플
        y16 = _resampler_32_to_16(y)
        out = y16.squeeze(0).detach().cpu().numpy().astype(np.float32, copy=False)

        # 길이 보정 (입력과 동일하게)
        if out.shape[0] != n_in:
            if out.shape[0] < n_in:
                out = np.pad(out, (0, n_in - out.shape[0]))
            else:
                out = out[:n_in]

        out_int16 = np.clip(out * 32768.0, -32768.0, 32767.0).astype(np.int16)

        if pcm_int16_16k.ndim == 2:
            out_int16 = out_int16.reshape(-1, 1)
        return out_int16

    except Exception as e:
        log.warning(f"enhance failed (passthrough): {type(e).__name__}: {e}")
        return pcm_int16_16k


# ========================================
# 버퍼드 스트리밍 인터페이스
# ========================================
class BufferedDenoiser:
    """
    LiveSession 의 처리 스레드에서 한 인스턴스를 만들고 매 블록마다 feed() 호출.
    chunk_samples 가 모이면 enhance 후 같은 길이의 int16 블록을 반환.
    100ms 짜리 raw 블록 5개를 모아 500ms 단위로 처리하는 구조.

    실시간 영향:
    - 입력→출력 지연: 평균 250ms (최대 500ms)
    - 카드 표시도 그만큼 늦어짐
    """
    DEFAULT_CHUNK_MS = 500

    def __init__(self, sample_rate: int = 16_000, chunk_ms: int = DEFAULT_CHUNK_MS):
        self.sample_rate = sample_rate
        self.chunk_samples = int(sample_rate * chunk_ms / 1000)
        # 입력은 mono 1-D int16 로 정규화해서 누적
        self._buffer = np.zeros(0, dtype=np.int16)
        self._is_2d_input = False  # 입력이 (N,1) 모양이면 출력도 그렇게

    def feed(self, pcm_int16: np.ndarray) -> List[np.ndarray]:
        """
        입력 블록을 누적, chunk 가 모이면 enhance 후 그 청크들의 리스트를 반환.
        반환 리스트의 각 원소는 chunk_samples 길이의 int16 (입력과 같은 채널 형태).
        """
        if pcm_int16 is None or pcm_int16.size == 0:
            return []

        if pcm_int16.ndim > 1:
            self._is_2d_input = True
            mono = pcm_int16[:, 0]
        else:
            mono = pcm_int16

        self._buffer = np.concatenate([self._buffer, mono.astype(np.int16, copy=False)])

        out: List[np.ndarray] = []
        while len(self._buffer) >= self.chunk_samples:
            chunk = self._buffer[: self.chunk_samples]
            self._buffer = self._buffer[self.chunk_samples:]
            enhanced = _enhance_chunk_int16(chunk)
            if self._is_2d_input and enhanced.ndim == 1:
                enhanced = enhanced.reshape(-1, 1)
            out.append(enhanced)
        return out

    def flush(self) -> Optional[np.ndarray]:
        """세션 종료 시 잔여 버퍼 처리. 길이 < chunk_samples 일 수 있음."""
        if len(self._buffer) == 0:
            return None
        # 너무 짧으면 (예: <100ms) 그냥 원본 반환 — 모델이 망가질 수 있음
        if len(self._buffer) < self.sample_rate // 10:  # 100ms 미만
            tail = self._buffer
            self._buffer = np.zeros(0, dtype=np.int16)
            if self._is_2d_input:
                tail = tail.reshape(-1, 1)
            return tail
        # 100ms ~ chunk 사이는 그래도 처리 시도
        chunk = self._buffer
        self._buffer = np.zeros(0, dtype=np.int16)
        enhanced = _enhance_chunk_int16(chunk)
        if self._is_2d_input and enhanced.ndim == 1:
            enhanced = enhanced.reshape(-1, 1)
        return enhanced
