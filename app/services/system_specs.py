"""
PC 사양 감지 + Whisper 모델 추천 (Phase 8C).
표준 라이브러리만 사용 (Windows 는 ctypes 로 RAM 조회).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

log = logging.getLogger("system_specs")


def _get_ram_gb_windows() -> Optional[float]:
    """Windows GlobalMemoryStatusEx 로 총 RAM GB 반환 (ctypes 만 사용, 외부 의존 없음)."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_uint32),
                ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("sullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        if not ok:
            return None
        return round(stat.ullTotalPhys / (1024**3), 1)
    except Exception as e:
        log.warning(f"RAM 조회 실패: {type(e).__name__}: {e}")
        return None


def _get_gpu_info() -> Optional[Dict[str, Any]]:
    """torch.cuda 로 NVIDIA GPU 정보. 없으면 None."""
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        idx = 0
        name = torch.cuda.get_device_name(idx)
        props = torch.cuda.get_device_properties(idx)
        return {
            "name": name,
            "vram_gb": round(props.total_memory / (1024**3), 1),
            "device_count": torch.cuda.device_count(),
        }
    except Exception as e:
        log.info(f"GPU 미감지 (정상): {type(e).__name__}: {e}")
        return None


def _recommend(cores: int, ram_gb: Optional[float], gpu: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    사양 → 모델 추천.
    Phase 8B 적용으로 GPU 가 감지되면 large-v3 까지 추천.

    추천 카드는 두 가지:
      - realtime: 녹음 중 실시간 처리용
      - post: 녹음 후 정확도 재처리용
    """
    ram = ram_gb or 8.0  # RAM 못 잡았으면 보수적으로 8GB 가정
    has_gpu = gpu is not None
    vram = (gpu or {}).get("vram_gb", 0) if has_gpu else 0

    if has_gpu and vram >= 10:
        # 고성능 GPU (RTX 4070Ti, 3080+, 4090 등)
        # ⚠ 한국어 짧은 발화는 medium 이 large-v3 보다 안정적 (large-v3 환각 多)
        # 긴 음성 후처리에서는 large-v3 가 빛남 → 역할 분리가 정답
        return {
            "realtime": "medium",
            "post": "large-v3",
            "tier": "gpu-high",
            "note": (
                f"NVIDIA GPU: {gpu['name']} ({vram:.0f}GB VRAM). "
                "한국어는 짧은 발화에서 medium 이 large-v3 보다 안정적입니다 "
                "(large-v3 는 짧은 입력에 환각 많음). "
                "실시간 medium + 후처리 large-v3 가 정확도 최상의 조합."
            ),
        }
    if has_gpu and vram >= 6:
        # 중급 GPU (RTX 3060 12GB, 4060, 2080 등)
        return {
            "realtime": "medium",
            "post": "large-v3",
            "tier": "gpu-mid",
            "note": (
                f"NVIDIA GPU: {gpu['name']} ({vram:.0f}GB VRAM). "
                "GPU 모드에서 medium 실시간 + large-v3 후처리 권장."
            ),
        }
    if has_gpu and vram >= 4:
        # 저급 GPU (RTX 3050 4GB, 1660 6GB 등) — small 실시간 + medium 후처리
        return {
            "realtime": "small",
            "post": "medium",
            "tier": "gpu-low",
            "note": (
                f"NVIDIA GPU: {gpu['name']} ({vram:.0f}GB VRAM). "
                "GPU VRAM 이 적어 small/medium 권장."
            ),
        }
    if cores >= 8 and ram >= 16:
        return {
            "realtime": "small",
            "post": "medium",
            "tier": "high-cpu",
            "note": "여유 있는 CPU 환경. 후처리에서 medium 까지 권장.",
        }
    if cores >= 4 and ram >= 8:
        return {
            "realtime": "small",
            "post": "medium",
            "tier": "mid-cpu",
            "note": "일반 노트북. small 실시간 + medium 후처리 조합이 가장 안정적입니다.",
        }
    if cores >= 2:
        return {
            "realtime": "base",
            "post": "small",
            "tier": "low-cpu",
            "note": "사양이 약한 PC. small 실시간이 버거울 수 있어 base 권장.",
        }
    return {
        "realtime": "tiny",
        "post": "small",
        "tier": "very-low",
        "note": "매우 낮은 사양. 정확도 한계 있음.",
    }


def get_specs() -> Dict[str, Any]:
    """프론트엔드에 노출할 시스템 사양 + 모델 추천 dict."""
    cores = os.cpu_count() or 1
    ram_gb = _get_ram_gb_windows() if os.name == "nt" else None
    gpu = _get_gpu_info()
    recommendation = _recommend(cores, ram_gb, gpu)
    return {
        "platform": os.name,
        "cpu_cores": cores,
        "ram_gb": ram_gb,
        "gpu": gpu,
        "recommendation": recommendation,
    }
