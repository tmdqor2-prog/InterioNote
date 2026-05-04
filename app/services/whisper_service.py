"""
faster-whisper 한국어 전사 서비스.
CPU int8. 모델 사이즈/키워드는 settings 에서 동적 로딩.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from app import config
from app.services import settings_service

log = logging.getLogger("whisper")


# ========================================
# 환각(hallucination) 감지 — 두 종류
# (A) 반복 환각: 같은 단어 도배 ("작품, 작품, 작품, ...")
# (B) silence/end-of-video 환각: 짧은 발화 + 정적 → Whisper 가 학습 데이터의
#     영상 끝맺음/자막 크레딧 표현으로 빠짐 ("고맙습니다", "자막제작가-XXX" 등)
# 두 종류 다 단일 카드 내부만 보고 판정. 카드 단위 emit 측에서 같은 텍스트
# 반복 dedup 은 일반 대화의 "네 네 네" 같은 정상 반복을 깨트릴 수 있어 안 함.
# ========================================
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")

# Whisper 가 정적/짧은 노이즈에서 자주 토하는 학습 데이터 잔재.
# 카드 전체가 이것과 정확히 일치하거나, 짧은 카드(≤30자)에서 50% 이상 차지하면 폐기.
# 한국 사용자 테스트(2026-04-26)에서 "고맙습니다" 무한반복 / "자막제작가-XXX" 확인됨.
_HALLUCINATION_BLACKLIST = {
    # 한국어 유튜브 끝맺음
    "고맙습니다", "고맙습니다.",
    "감사합니다", "감사합니다.",
    "시청해주셔서 감사합니다", "시청해주셔서 감사합니다.",
    "구독과 좋아요 부탁드립니다", "구독 좋아요 부탁드립니다",
    "다음 영상에서 만나요", "다음 영상에서 만나요.",
    # 음악/효과음 placeholder (Whisper 가 종종 토함)
    "음악", "(음악)", "[음악]", "MR", "(MR)",
    # 영어 fallback (한국어 모델도 가끔 영어로 출력)
    "Thank you for watching", "Thank you for watching.",
    "Thanks for watching", "Thanks for watching.",
    "Please subscribe", "Please like and subscribe",
    "you", "You", "You.", "Yeah.", "Yeah",
    "Bye", "Bye.", "Bye-bye.",
}

# 자막 크레딧 패턴 — 카드 전체가 이런 형태면 폐기
# 예) "자막제작가-정선호", "제작진-홍길동", "번역: XXX", "자막: YYY"
_SUBTITLE_CREDIT_PATTERNS = [
    re.compile(r"^\s*자막\s*제작"),       # 자막제작가, 자막 제작자
    re.compile(r"^\s*제작진\s*[-:·,]"),   # 제작진-XXX
    re.compile(r"^\s*번역\s*[-:·]"),      # 번역 - XXX
    re.compile(r"^\s*자막\s*[-:·]"),      # 자막: XXX
    re.compile(r"시청\s*해\s*주셔서\s*감사"),  # 시청해주셔서 감사
    re.compile(r"구독\s*(과|및|,|\s)+좋아요"),  # 구독과 좋아요
]


def _is_known_silence_hallucination(text: str) -> bool:
    """짧은 정적/노이즈 구간에서 Whisper 가 학습 데이터 끝맺음으로 빠지는 패턴.
    실제 상담에서 손님이 진짜 '감사합니다' 라고 한 것도 같이 걸리는 trade-off 있음.
    그러나 환각으로 같은 표현이 수십 번 도배되는 것보다는 낫다고 판단."""
    if not text:
        return False
    s = text.strip()
    if not s:
        return False
    # 1) 짧은 카드(≤25자) 가 블랙리스트와 정확 일치
    if len(s) <= 25 and s in _HALLUCINATION_BLACKLIST:
        return True
    # 2) 짧은 카드(≤30자) 에서 블랙리스트 phrase 가 50% 이상 차지
    if len(s) <= 30:
        for phrase in _HALLUCINATION_BLACKLIST:
            if phrase and phrase in s and len(phrase) / len(s) >= 0.5:
                return True
    # 3) 자막/제작 크레딧 패턴
    for pat in _SUBTITLE_CREDIT_PATTERNS:
        if pat.search(s):
            return True
    return False


# Phase 8B 추가: medium 모델이 짧은 입력에서 인사말 여러 개를
# "감사합니다. 반갑습니다. 고맙습니다." 처럼 체인으로 출력하는 패턴.
# 단일 발화는 통과시키고 (예: 진짜 "안녕하세요"), 2개 이상 묶이면 폐기.
_HALLUCINATION_CHAIN_PHRASES = {
    "감사합니다", "고맙습니다", "반갑습니다",
    "안녕하세요", "안녕히가세요", "안녕히계세요",
    "잘부탁드립니다", "잘부탁합니다",
    "수고하셨습니다", "수고하세요",
    "다음에봐요", "다음에뵐게요", "또봐요", "또뵐게요",
    "감사해요", "고마워요",
    # 영어 outro 도 같이
    "thankyou", "thanks", "bye", "byebye",
}

_PHRASE_NORMALIZE_RE = re.compile(r"[\s.!?,]+")


def _normalize_for_chain(s: str) -> str:
    """공백/구두점 제거 후 비교용 정규화 (소문자도 통일)."""
    return _PHRASE_NORMALIZE_RE.sub("", s).lower()


def _is_chained_hallucination(text: str) -> bool:
    """
    짧은 인사/감사 표현이 2개 이상 . ! ? 로 연결된 카드는 환각으로 본다.
    medium 모델이 짧은 음성을 받았을 때 자주 만드는 패턴.
      "감사합니다. 반갑습니다. 고맙습니다."  → True
      "안녕하세요"                              → False (단독 인사는 정상)
      "주방 어떻게 할까요?"                     → False (인사 풀에 없음)
    """
    if not text or len(text) > 100:
        return False
    sentences = re.split(r"[.!?\n]+", text)
    norms = [_normalize_for_chain(s) for s in sentences]
    norms = [n for n in norms if n]  # 빈 토막 제거
    if len(norms) < 2:
        return False
    chain_hits = sum(1 for n in norms if n in _HALLUCINATION_CHAIN_PHRASES)
    # 2개 이상의 sentence 가 모두 인사 풀에 속하면 환각
    return chain_hits >= 2 and chain_hits == len(norms)


def _is_repetition_hallucination(text: str) -> bool:
    """반복 환각 + silence 환각 + 인사 체인 환각 통합 판정."""
    if not text:
        return False
    if _is_known_silence_hallucination(text):
        return True
    if _is_chained_hallucination(text):
        return True
    # 토큰 빈도 분석 (작품 작품 작품 ... 패턴)
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return False
    if len(tokens) <= 2:
        return len(set(tokens)) == 1 and len(tokens) >= 2 and len(tokens[0]) <= 4
    counter = Counter(tokens)
    most_common_count = counter.most_common(1)[0][1]
    return most_common_count / len(tokens) >= 0.6


# Public alias for use by other modules (예: retranscribe_service)
is_repetition_hallucination = _is_repetition_hallucination


# ========================================
# 멀티 모델 캐시 (live + post-processing 공존)
# ========================================
_live_model = None
_loaded_live_size: Optional[str] = None
_loaded_live_device: Optional[str] = None  # Phase 8B: 디바이스 변경도 재로딩 트리거
_post_models: Dict[str, Any] = {}  # key = (size, device)
_lock = threading.Lock()
_cuda_dll_path_setup_done = False


def _setup_cuda_dll_paths() -> None:
    """
    Phase 8B — Windows 에서 pip 설치한 nvidia-cublas-cu12 / nvidia-cudnn-cu12 의
    .dll 들이 ctranslate2 에 의해 발견되도록 PATH 에 추가.
    시스템 CUDA Toolkit 설치를 안 했을 때 필요. 한 번만 실행.

    v2.4.5: 번들 모드 (PyInstaller --onedir) 도 지원.
    번들에서는 nvidia DLL 들이 _internal/ 의 여러 위치에 들어갈 수 있어 모두 검색.
    """
    global _cuda_dll_path_setup_done
    if _cuda_dll_path_setup_done:
        return
    _cuda_dll_path_setup_done = True
    if os.name != "nt":
        return
    try:
        import sys as _sys

        # 검색 후보 위치 (dev + bundled 양쪽 대응)
        candidate_roots: list[Path] = []

        # 1) dev 모드: venv/Lib/site-packages
        try:
            sp = Path(_sys.executable).parent.parent / "Lib" / "site-packages"
            candidate_roots.append(sp)
        except Exception:
            pass

        # 2) PyInstaller --onedir 번들: _internal 디렉터리
        if getattr(_sys, "frozen", False):
            # sys.executable = install_dir/InterioNote.exe → _internal 은 같은 폴더 옆
            try:
                exe_parent = Path(_sys.executable).parent
                internal = exe_parent / "_internal"
                if internal.is_dir():
                    candidate_roots.append(internal)
            except Exception:
                pass
            # _MEIPASS (--onefile 또는 일부 --onedir 환경) 도 후보로
            meipass = getattr(_sys, "_MEIPASS", None)
            if meipass:
                try:
                    candidate_roots.append(Path(meipass))
                except Exception:
                    pass

        # 각 root 안에서 nvidia/<lib>/bin 또는 평탄화된 위치 검색
        nvidia_libs = ["cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"]
        candidates: list[Path] = []
        for root in candidate_roots:
            for lib in nvidia_libs:
                candidates.append(root / "nvidia" / lib / "bin")
            # 번들에서 평탄화됐을 수 있는 위치도 시도
            candidates.append(root)  # 루트 자체에 .dll 들이 있을 수 있음

        added = []
        for d in candidates:
            try:
                if not d.is_dir():
                    continue
            except Exception:
                continue
            try:
                os.add_dll_directory(str(d))
            except Exception:
                pass
            if str(d) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            added.append(str(d))

        if added:
            log.info(f"CUDA DLL paths added: {len(added)} dirs (frozen={getattr(_sys, 'frozen', False)})")
            for p in added[:8]:
                log.info(f"  - {p}")
        else:
            log.info("CUDA DLL 후보 디렉터리 미감지 — 시스템 PATH 또는 CPU 모드로 폴백")
    except Exception as e:
        log.warning(f"CUDA DLL path setup 실패 (CPU 폴백): {type(e).__name__}: {e}")


def _resolve_device() -> str:
    """
    settings 의 device 설정 → 실제 사용할 device 문자열 ('cpu' | 'cuda').
    'auto' 면 GPU 가능 여부 확인. 'cuda' 명시인데 불가능하면 RuntimeError.
    """
    pref = settings_service.get_whisper_device()  # 'auto' | 'cpu' | 'cuda'
    if pref == "cpu":
        return "cpu"

    # GPU 가능 여부 확인 (torch.cuda 우선, 실패 시 ctranslate2 시도)
    cuda_ok = False
    try:
        import torch
        cuda_ok = bool(torch.cuda.is_available())
    except Exception:
        cuda_ok = False

    if pref == "cuda" and not cuda_ok:
        raise RuntimeError(
            "GPU 모드(cuda) 로 설정됐지만 CUDA 사용 불가. "
            "torch CUDA 빌드 + nvidia-cublas-cu12 + nvidia-cudnn-cu12 가 설치되어 있어야 합니다. "
            "설정에서 'CPU' 또는 '자동' 으로 변경하세요."
        )
    return "cuda" if cuda_ok else "cpu"


def _build_model(size: str, device: Optional[str] = None):
    """동일 옵션의 WhisperModel 인스턴스를 새로 만든다.
    device 가 None 이면 settings 따라 자동. compute_type 은 device 에 맞게 자동 선택.
    """
    from faster_whisper import WhisperModel

    _setup_cuda_dll_paths()
    if device is None:
        device = _resolve_device()
    # 디바이스별 quantization 선택
    # - GPU: float16 (큰 모델도 빠르게, VRAM 적게)
    # - CPU: int8 (메모리 효율 + 적당한 속도)
    if device == "cuda":
        compute_type = "float16"
        cpu_threads = 0  # GPU 모드에서는 무관
    else:
        compute_type = "int8"
        cpu_threads = 4

    cache = config.MODELS_CACHE_DIR / "whisper"
    cache.mkdir(parents=True, exist_ok=True)
    log.info(f"Loading faster-whisper {size} ({device} {compute_type})...")
    try:
        m = WhisperModel(
            size,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            num_workers=1,
            download_root=str(cache),
        )
    except Exception as e:
        # GPU 로드 실패 → 자동 CPU 폴백 (강제 cuda 모드면 실패)
        if device == "cuda" and settings_service.get_whisper_device() == "auto":
            log.warning(
                f"CUDA 로드 실패, CPU 로 폴백: {type(e).__name__}: {e}"
            )
            return _build_model(size, device="cpu")
        raise
    log.info(f"faster-whisper {size} loaded ({device} {compute_type})")
    return m


def set_model_size(size: str) -> None:
    """런타임에 교체. 다음 get_whisper() 에서 재로딩."""
    global _live_model, _loaded_live_size, _loaded_live_device
    settings_service.set_whisper_model_size(size)
    with _lock:
        _live_model = None
        _loaded_live_size = None
        _loaded_live_device = None


def reset_models_for_device_change() -> None:
    """Phase 8B — device 설정 변경 시 호출. 모든 캐시된 모델을 폐기 → 다음 호출에서 새 device 로 재로딩."""
    global _live_model, _loaded_live_size, _loaded_live_device, _post_models
    with _lock:
        _live_model = None
        _loaded_live_size = None
        _loaded_live_device = None
        _post_models = {}


def get_loaded_model_size() -> Optional[str]:
    return _loaded_live_size


def get_loaded_device() -> Optional[str]:
    return _loaded_live_device


def get_whisper():
    """
    실시간 (live) Whisper 모델 싱글톤. settings.whisper.model_size + device 를 따라감.
    """
    global _live_model, _loaded_live_size, _loaded_live_device
    target_size = settings_service.get_whisper_model_size()
    target_device = _resolve_device()

    if (_live_model is not None
            and _loaded_live_size == target_size
            and _loaded_live_device == target_device):
        return _live_model
    with _lock:
        if (_live_model is not None
                and _loaded_live_size == target_size
                and _loaded_live_device == target_device):
            return _live_model
        # post 캐시에 같은 (size, device) 가 있으면 재사용
        cache_key = (target_size, target_device)
        if cache_key in _post_models:
            _live_model = _post_models[cache_key]
        else:
            _live_model = _build_model(target_size, device=target_device)
        _loaded_live_size = target_size
        _loaded_live_device = target_device
    return _live_model


def get_post_whisper(size: str):
    """
    후처리(녹음 종료 후 재전사) 전용 모델 캐시.
    live 모델과 다른 사이즈를 동시에 메모리에 올릴 때 사용.
    같은 (size, device) 가 live 에 이미 로드되어 있으면 그걸 재사용.
    """
    target_device = _resolve_device()
    cache_key = (size, target_device)
    if cache_key in _post_models:
        return _post_models[cache_key]
    with _lock:
        if cache_key in _post_models:
            return _post_models[cache_key]
        if (_loaded_live_size == size
                and _loaded_live_device == target_device
                and _live_model is not None):
            _post_models[cache_key] = _live_model
            return _live_model
        _post_models[cache_key] = _build_model(size, device=target_device)
        return _post_models[cache_key]


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
