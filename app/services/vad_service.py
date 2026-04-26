"""
Silero VAD 스트리밍 래퍼.
512 샘플(@16kHz) 청크 단위로 피드 → speech_start/end 이벤트 → 완결된 발화 세그먼트 emit.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

import numpy as np

log = logging.getLogger("vad")

_model = None
_model_lock = threading.Lock()


def get_vad_model():
    """Silero VAD 싱글톤. 첫 호출 시 onnx 모델 다운로드(~1MB)."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        from silero_vad import load_silero_vad
        log.info("Loading silero VAD (onnx)...")
        _model = load_silero_vad(onnx=True)
        log.info("silero VAD loaded")
    return _model


class StreamingVAD:
    """
    누적 오디오(float32)를 512 샘플 단위로 VAD 에 넣는다.
    feed() 가 호출될 때마다, 종료된 발화 세그먼트 리스트를 반환한다.
    finalize() 는 stop 시점에 진행 중이던 발화를 마무리.
    """
    VAD_CHUNK = 512  # silero 고정 (16kHz 기준 32ms)

    def __init__(
        self,
        sample_rate: int = 16_000,
        threshold: float = 0.5,
        min_silence_ms: int = 500,
        speech_pad_ms: int = 30,
    ):
        from silero_vad import VADIterator
        self.sample_rate = sample_rate
        model = get_vad_model()
        self._iter = VADIterator(
            model,
            threshold=threshold,
            sampling_rate=sample_rate,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        self._buffer = np.empty(0, dtype=np.float32)  # leftover < 512
        self._in_speech = False
        self._speech_start_sample: Optional[int] = None
        self._speech_audio: List[np.ndarray] = []
        self._total_samples = 0

    def feed(self, pcm_int16: np.ndarray) -> List[Dict]:
        """
        mono int16 배열을 받아 float32 로 정규화한 뒤 VAD 에 입력.
        완결된 발화가 있으면 리스트로 반환:
           [{"start_sample": int, "end_sample": int, "audio": np.ndarray(float32)}]
        """
        if pcm_int16.size == 0:
            return []
        if pcm_int16.ndim > 1:
            pcm_int16 = pcm_int16[:, 0]
        audio = pcm_int16.astype(np.float32) / 32768.0
        self._buffer = np.concatenate([self._buffer, audio])

        completed: List[Dict] = []
        while len(self._buffer) >= self.VAD_CHUNK:
            chunk = self._buffer[:self.VAD_CHUNK]
            self._buffer = self._buffer[self.VAD_CHUNK:]

            # silero VADIterator 는 numpy 또는 torch 둘 다 받음
            try:
                ev = self._iter(chunk)
            except Exception as e:
                # torch 텐서를 요구하는 환경 폴백
                import torch
                ev = self._iter(torch.from_numpy(chunk))

            if self._in_speech:
                self._speech_audio.append(chunk)

            if ev is not None:
                if "start" in ev:
                    self._in_speech = True
                    self._speech_start_sample = self._total_samples
                    # speech_pad 덕에 시작 지점에 현재 청크도 포함
                    self._speech_audio = [chunk]
                elif "end" in ev:
                    self._in_speech = False
                    if self._speech_audio:
                        seg_audio = np.concatenate(self._speech_audio)
                        completed.append({
                            "start_sample": int(self._speech_start_sample or 0),
                            "end_sample": int(self._total_samples + self.VAD_CHUNK),
                            "audio": seg_audio,
                        })
                    self._speech_audio = []
                    self._speech_start_sample = None

            self._total_samples += self.VAD_CHUNK
        return completed

    def finalize(self) -> List[Dict]:
        """stop 시점에 아직 진행 중이던 발화를 마무리해 반환."""
        if not self._in_speech or not self._speech_audio:
            return []
        seg_audio = np.concatenate(self._speech_audio)
        segment = {
            "start_sample": int(self._speech_start_sample or 0),
            "end_sample": int(self._total_samples),
            "audio": seg_audio,
        }
        self._in_speech = False
        self._speech_audio = []
        self._speech_start_sample = None
        return [segment]
