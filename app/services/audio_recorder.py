"""
마이크 I/O (Phase 2).
- sounddevice InputStream 콜백은 절대 블록되면 안 됨 → out_queue 에 복사만 넣음
- 이후 처리(WAV 쓰기, VAD, Whisper)는 별도 스레드에서 소비
"""
from __future__ import annotations

import queue
from typing import Any, Dict, List, Optional

import numpy as np
# sounddevice 는 import 시점에 PortAudio 를 초기화해 CPU / 오디오 백엔드 리소스를 선점함.
# 앱 시작 시 불필요한 초기화를 막기 위해 실제로 필요한 시점(첫 녹음·장치 목록 조회)에만 로드.
_sd = None


def _get_sd():
    """sounddevice 지연 로드 — 첫 호출 시에만 import."""
    global _sd
    if _sd is None:
        import sounddevice as sd  # noqa: PLC0415
        _sd = sd
    return _sd


# ========================================
# 고정 포맷 (silero/Whisper 모두 16kHz 기준)
# ========================================
SAMPLE_RATE = 16_000
CHANNELS = 1
DTYPE = "int16"
BLOCKSIZE = 1_600   # 100ms @ 16kHz
QUEUE_MAX = 500     # ~50초 버퍼 한계


def list_input_devices() -> List[Dict[str, Any]]:
    """마이크 장치 목록."""
    sd = _get_sd()
    try:
        default_idx = sd.default.device[0] if sd.default.device else None
    except Exception:
        default_idx = None

    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        if int(dev.get("max_input_channels", 0) or 0) <= 0:
            continue
        devices.append({
            "id": idx,
            "name": dev.get("name", f"device {idx}"),
            "max_input_channels": int(dev.get("max_input_channels", 0)),
            "default_samplerate": int(dev.get("default_samplerate") or 0),
            "is_default": (idx == default_idx),
        })
    return devices


class Recorder:
    """
    InputStream 을 열어 콜백 안에서 out_queue 에 int16 np.ndarray(shape=(N,1)) 를 넣는다.
    WAV 쓰기/VAD 는 LiveSession 이 담당.
    """
    def __init__(
        self,
        device_id: Optional[int],
        out_queue: "queue.Queue[np.ndarray]",
    ):
        self.device_id = device_id
        self.out_queue = out_queue
        self._stream = None
        self._dropped = 0

    @property
    def dropped(self) -> int:
        return self._dropped

    def _callback(self, indata, frames, time_info, status):  # noqa: D401
        try:
            self.out_queue.put_nowait(indata.copy())
        except queue.Full:
            self._dropped += 1

    def start(self) -> None:
        sd = _get_sd()
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=BLOCKSIZE,
            device=self.device_id,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
