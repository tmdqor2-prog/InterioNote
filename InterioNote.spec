# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 빌드 스펙 — InterioNote (Phase 7B-1).

빌드:
    pyinstaller --noconfirm InterioNote.spec

결과:
    dist\\InterioNote\\InterioNote.exe  + dist\\InterioNote\\_internal\\...

배포 방식:
    Phase 7B-2 의 Inno Setup 이 dist\\InterioNote\\ 폴더 전체를
    InterioNoteSetup.exe 로 패키징.

런타임 데이터 위치 (Phase 7A):
    %APPDATA%\\InterioNote\\        ← DB
    %LOCALAPPDATA%\\InterioNote\\   ← 모델 캐시 + 임시 녹음 (첫 실행 시 다운로드)
"""
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    collect_dynamic_libs,
)


# ----------------------------------------
# 까다로운 라이브러리는 collect_all 로 통째로
# ----------------------------------------
datas = []
binaries = []
hiddenimports = []

for pkg in [
    "torch",
    "torchaudio",
    "ctranslate2",
    "faster_whisper",
    "silero_vad",
    "lameenc",
    "soundfile",
    "sounddevice",
    "onnxruntime",
    "huggingface_hub",
    "tokenizers",
    "fastapi",
    "uvicorn",
    "starlette",
    "pydantic",
    "pydantic_core",
    "httpx",
    "h11",
    "h2",
    "anyio",
    "sniffio",
    "jinja2",
    "markupsafe",
    "webview",          # pywebview 패키지 import 이름
    "omegaconf",
    "antlr4",
    "numpy",
]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec WARN] collect_all({pkg}) skipped: {e}")


# ----------------------------------------
# Uvicorn / Starlette 동적 import 들 (PyInstaller가 자동 감지 못함)
# ----------------------------------------
hiddenimports += [
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.logging",
    "encodings.idna",
    "encodings.utf_8",
    "encodings.cp949",
]


# ----------------------------------------
# 앱 정적 파일 (HTML, 이미지 등)
# v2.4.2: version.json 도 데이터로 — 빠른 업데이트가 교체 가능하도록
# ----------------------------------------
datas += [
    ("app/static", "app/static"),
    ("app/version.json", "app"),  # → _internal/app/version.json
]


# ----------------------------------------
# 안 쓰는 거 제외 (용량 ↓)
# v3.5.5: 추가 excludes 로 배포 사이즈 약 100~200MB 감소 시도
# ----------------------------------------
excludes = [
    # GUI 라이브러리 (사용 안 함)
    "matplotlib",
    "tkinter",
    "PIL",
    "Pillow",
    "cv2",
    # 데이터 분석 (사용 안 함)
    "pandas",
    "scipy",
    # 개발 도구 (사용 안 함)
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "sphinx",
    "setuptools",
    "wheel",
    "pip",
    "pkg_resources",
    # PyTorch / NumPy 의 테스트·문서·F2PY (런타임 X)
    "torch.testing",
    "torch.distributions.constraints",  # large but rarely used
    "torch.utils.tensorboard",
    "torch.utils.benchmark",
    "torchaudio.datasets",
    "torchaudio.examples",
    "numpy.testing",
    "numpy.tests",
    "numpy.f2py",
    "numpy.distutils",
    # Pywebview 의 비-Windows 백엔드들
    "webview.platforms.cocoa",
    "webview.platforms.gtk",
    "webview.platforms.qt",
    "webview.platforms.android",
]


a = Analysis(
    ["InterioNote.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)


# ----------------------------------------
# v3.5.5: 후처리 — datas/binaries 에서 큰 비-필수 파일 제거
# 효과: 약 50~100MB 감소 (test 디렉토리, .pyi 타입 스텁, locale 등)
# ----------------------------------------
def _strip_unwanted(items, patterns):
    """items 의 첫 요소(target path) 가 patterns 중 하나를 포함하면 제외."""
    out = []
    for it in items:
        target = (it[0] if it else "").replace("\\", "/").lower()
        if any(p in target for p in patterns):
            continue
        out.append(it)
    return out


_DATA_BLOCK = [
    "/tests/", "/test/",       # 모든 패키지의 테스트
    "/docs/", "/doc/",         # 문서
    "/examples/",              # 예제
    "/__pycache__/",           # PyInstaller 가 보통 빼지만 안전망
    ".pyi",                    # 타입 스텁 (런타임 무관)
    ".pdb",                    # 디버그 심볼
    "/locales/cs.", "/locales/de.", "/locales/es.", "/locales/fr.",
    "/locales/it.", "/locales/ja.", "/locales/pl.", "/locales/pt.",
    "/locales/ru.", "/locales/zh-",  # 안 쓰는 언어 locale (한국어/영어만 유지)
]
_BIN_BLOCK = [
    "/tests/", "/test/",
]
a.datas = _strip_unwanted(a.datas, _DATA_BLOCK)
a.binaries = _strip_unwanted(a.binaries, _BIN_BLOCK)


pyz = PYZ(a.pure, a.zipped_data)

# Phase 7B-2 v2 (2026-04-27 진단 결과):
#  - console=False (windowed) 부트로더 runw.exe 가 Windows 11 26200+ 에서
#    silent 차단됨 (Defender 와 다른 새 보안 휴리스틱). 작업관리자에 프로세스도 안 뜸.
#  - 해결: console=True 로 빌드 (이건 차단 안 됨) + hide_console='hide-early' 로
#    실행 즉시 콘솔창 숨김. 사용자 체감은 windowed 모드와 동일.
# (디버그가 필요할 땐 hide_console 줄을 주석 처리해서 콘솔 보이게 하면 됨)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InterioNote",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # 안정성 우선
    console=True,                   # ✅ 차단 회피
    hide_console='hide-early',      # ✅ 콘솔창 자동 숨김 (PyInstaller 6+)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                      # icon 파일 있으면 'icon.ico' 등 지정
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="InterioNote",
)
