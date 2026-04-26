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
# ----------------------------------------
datas += [
    ("app/static", "app/static"),
]


# ----------------------------------------
# 안 쓰는 거 제외 (용량 ↓)
# ----------------------------------------
excludes = [
    "matplotlib",
    "tkinter",
    "PIL",
    "Pillow",
    "pandas",
    "scipy",
    "cv2",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "sphinx",
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

pyz = PYZ(a.pure, a.zipped_data)

# 프로덕션: console=False — 검은 cmd 창 안 뜸. 앱 창만.
# (디버그 필요할 때 이 값을 True 로 바꾼 뒤 재빌드)
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
    console=False,                  # ✅ 프로덕션
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
