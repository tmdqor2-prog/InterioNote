"""
WAV → MP3 변환 (lameenc).
순수 pip 패키지, 외부 ffmpeg 없이 동작. 16kHz mono int16 WAV 기준.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf


CHUNK_SECONDS = 10  # 한 번에 인코딩할 오디오 길이 (메모리 관리)


def wav_to_mp3(
    wav_path: Path,
    mp3_path: Path,
    bitrate_kbps: int = 128,
    quality: int = 2,
) -> dict:
    """
    16kHz mono WAV → MP3. 실패 시 예외. 성공 시 파일 크기 등 메타 dict 반환.
    lameenc 는 동기 API 이므로 호출 스레드에서 완료.
    """
    import lameenc  # 로컬 import — warmup 시점에 불필요하게 로드하지 않음

    if not wav_path.exists():
        raise FileNotFoundError(f"WAV 파일이 없습니다: {wav_path}")

    # soundfile 로 int16 로 읽어옴 (메모리 사용 ~1.8MB/분 @16kHz)
    with sf.SoundFile(str(wav_path), mode="r") as f:
        sr = f.samplerate
        channels = f.channels
        total_frames = f.frames

        encoder = lameenc.Encoder()
        encoder.set_bit_rate(bitrate_kbps)
        encoder.set_in_sample_rate(sr)
        encoder.set_channels(1)  # 우리는 mono 로 저장
        encoder.set_quality(quality)  # 2=고품질, 7=저품질

        chunk_frames = sr * CHUNK_SECONDS
        mp3_chunks: list[bytes] = []
        while True:
            block = f.read(chunk_frames, dtype="int16")
            if block is None or (hasattr(block, "size") and block.size == 0):
                break
            if block.ndim > 1:
                block = block[:, 0]  # mono 채널만
            # 오디오가 int16 np.ndarray → tobytes()
            mp3_chunks.append(encoder.encode(block.astype(np.int16).tobytes()))

        mp3_chunks.append(encoder.flush())

    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_path.write_bytes(b"".join(mp3_chunks))

    return {
        "mp3_path": str(mp3_path),
        "size_bytes": mp3_path.stat().st_size,
        "input_sample_rate": sr,
        "input_channels": channels,
        "input_frames": total_frames,
        "bitrate_kbps": bitrate_kbps,
    }
