"""
Phase 8D — 인앱 빠른 업데이트 서비스.

흐름:
1. /api/app/check-update 로 GitHub Release 의 update zip URL 확인
2. download_and_stage(url) — zip 다운로드 → SHA256/manifest 검증 → staging 폴더에 풀기
3. trigger_apply() — update_apply.bat 동적 생성 → 실행 → 앱 종료 트리거
4. update_apply.bat: InterioNote.exe 종료 대기 → 백업 → 교체 → 재실행 → 자기 자신 삭제
5. 새 버전 첫 실행 시 last_update.txt 보고 "업데이트 완료" 토스트

dev 모드 (frozen=False) 에선 동작 안 함. 명확한 에러 메시지로 안내.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app import config

log = logging.getLogger("quick_update")


# ============================================
# 경로 헬퍼
# ============================================
def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def get_install_dir() -> Optional[Path]:
    """현재 실행 중인 InterioNote.exe 가 있는 install dir.
    PyInstaller frozen 일 때만 의미. dev 모드는 None."""
    if not is_frozen():
        return None
    return Path(sys.executable).parent


def get_internal_app_dir() -> Optional[Path]:
    """v2.4.2: PyInstaller 의 실제 데이터 파일 위치 = install_dir/_internal/app/
    이게 정적 파일/version.json 의 진짜 거주지. 빠른 업데이트는 여기를 교체해야 효과 있음.
    """
    install_dir = get_install_dir()
    if install_dir is None:
        return None
    return install_dir / "_internal" / "app"


def get_helper_log_path() -> Path:
    """v2.4.2: helper 가 매 실행마다 진단 로그 기록."""
    return config.USER_CACHE_DIR / "update_apply.log"


def get_staging_dir() -> Path:
    d = config.USER_CACHE_DIR / "update_staging"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_helper_path() -> Path:
    return config.USER_CACHE_DIR / "update_apply.bat"


def get_last_update_marker() -> Path:
    """업데이트 직후 새 버전이 첫 실행될 때 읽는 마커 파일."""
    return config.USER_CACHE_DIR / "last_update.txt"


def get_zip_download_path(version: str) -> Path:
    """다운받는 동안 임시 보관할 zip 경로."""
    return config.USER_CACHE_DIR / f"download-{version}.zip"


def get_backup_dir() -> Path:
    """업데이트 적용 시 옛 app/ 을 백업하는 위치."""
    return config.USER_CACHE_DIR / "update_backup"


# ============================================
# semver 비교
# ============================================
def _to_tuple(v: str) -> tuple:
    v = (v or "0").lstrip("v").lstrip("V")
    parts = []
    for x in v.split("."):
        try:
            parts.append(int(x))
        except ValueError:
            break
    return tuple(parts) or (0,)


def version_ge(a: str, b: str) -> bool:
    """a >= b ?"""
    return _to_tuple(a) >= _to_tuple(b)


# ============================================
# 다운로드
# ============================================
def download_zip(url: str, dest: Path, progress_cb=None) -> int:
    """url → dest 로 다운로드. progress_cb(downloaded, total) 호출."""
    if dest.exists():
        dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    downloaded = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as r:
        r.raise_for_status()
        try:
            total = int(r.headers.get("Content-Length") or 0)
        except (ValueError, TypeError):
            total = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=64 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    try:
                        progress_cb(downloaded, total)
                    except Exception:
                        pass
    return dest.stat().st_size


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ============================================
# manifest 검증
# ============================================
def read_manifest_from_zip(zip_path: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "update_manifest.json" not in names:
            raise ValueError("update_manifest.json 이 zip 에 없음 — 잘못된 빠른 업데이트 패키지")
        with z.open("update_manifest.json") as f:
            return json.load(f)


def validate_compatibility(manifest: Dict[str, Any], current_app_version: str) -> None:
    """비호환이면 ValueError 예외."""
    target = manifest.get("version") or "?"
    min_app = manifest.get("min_app_version") or "0.0.0"
    if not version_ge(current_app_version, min_app):
        raise ValueError(
            f"빠른 업데이트 불가: 현재 버전 {current_app_version} 이 너무 옛버전입니다.\n"
            f"이 업데이트 (v{target}) 는 최소 v{min_app} 부터 적용 가능합니다.\n"
            f"전체 인스톨러를 다운로드해서 새로 설치해주세요."
        )


# ============================================
# 풀기
# ============================================
def extract_to_staging(zip_path: Path, staging: Path) -> int:
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(staging)
        return len(z.namelist())


# ============================================
# helper .bat 생성 (영문 전용 — cmd cp949 호환)
# ============================================
def write_apply_helper(
    install_dir: Path,
    staging: Path,
    helper_path: Path,
    target_version: str,
    current_pid: int,
) -> None:
    """
    update_apply.bat 동적 생성 (v2.4.2 재설계).

    이전 버그: install_dir\\app 을 교체했으나 PyInstaller 의 실제 데이터 파일 위치는
    install_dir\\_internal\\app 이라 효과 없었음. 이번엔 _internal\\app 을 타겟.

    동작:
     1. InterioNote.exe (PID) 종료 대기 (최대 60초)
     2. install_dir\\_internal\\app 을 backup 으로 보관
     3. staging\\app 의 내용을 install_dir\\_internal\\app 으로 mirror
     4. last_update.txt 작성
     5. InterioNote.exe 재실행
     6. 자기 자신 삭제
    실패 시 backup 에서 롤백 후 옛 버전 재실행.

    매 단계 진단 로그를 update_apply.log 에 append. 추후 문제 시 확인 가능.
    """
    backup_dir = get_backup_dir()
    last_marker = get_last_update_marker()
    log_path = get_helper_log_path()
    exe_path = install_dir / "InterioNote.exe"
    target_app_dir = install_dir / "_internal" / "app"  # v2.4.2 핵심 변경

    content = f"""@echo off
REM ============================================================
REM  InterioNote quick-update apply helper (v2.4.2)
REM  target version: {target_version}
REM  Replaces _internal\\app files, then relaunches.
REM  ASCII-only. All steps logged to update_apply.log.
REM ============================================================
setlocal

set "INSTALL_DIR={install_dir}"
set "STAGING={staging}"
set "BACKUP_DIR={backup_dir}"
set "TARGET_APP={target_app_dir}"
set "EXE_PATH={exe_path}"
set "LAST_MARKER={last_marker}"
set "LOG={log_path}"
set "TARGET_PID={current_pid}"

REM Reset log
echo === update_apply.bat START === > "%LOG%"
echo time:        %DATE% %TIME% >> "%LOG%"
echo target ver:  {target_version} >> "%LOG%"
echo install dir: %INSTALL_DIR% >> "%LOG%"
echo target app:  %TARGET_APP% >> "%LOG%"
echo staging:     %STAGING% >> "%LOG%"
echo backup:      %BACKUP_DIR% >> "%LOG%"
echo exe path:    %EXE_PATH% >> "%LOG%"
echo target pid:  %TARGET_PID% >> "%LOG%"
echo. >> "%LOG%"

REM 1. Wait for InterioNote.exe (PID) to exit (max ~30 seconds)
echo [1] waiting for PID %TARGET_PID% to exit... >> "%LOG%"
set /a WAIT_COUNT=0
:wait_loop
tasklist /FI "PID eq %TARGET_PID%" 2>NUL | findstr /C:"%TARGET_PID%" >NUL
if errorlevel 1 goto :exited
set /a WAIT_COUNT+=1
if %WAIT_COUNT% GEQ 30 (
    echo [1] timeout -- proceeding anyway >> "%LOG%"
    goto :exited
)
ping -n 2 127.0.0.1 >NUL
goto :wait_loop

:exited
echo [1] PID gone, waited %WAIT_COUNT% sec >> "%LOG%"
ping -n 3 127.0.0.1 >NUL

REM Sanity check input paths
if not exist "%TARGET_APP%" (
    echo [PRE] FAIL: target app dir missing -- %TARGET_APP% >> "%LOG%"
    echo [PRE] aborting without rollback >> "%LOG%"
    goto :launch_only
)
if not exist "%STAGING%\\app" (
    echo [PRE] FAIL: staging\\app missing -- %STAGING%\\app >> "%LOG%"
    echo [PRE] aborting without rollback >> "%LOG%"
    goto :launch_only
)

REM 2. Backup current _internal\\app (ignore failures, backup is best-effort)
echo [2] backing up current _internal\\app to backup... >> "%LOG%"
if exist "%BACKUP_DIR%" rmdir /s /q "%BACKUP_DIR%"
mkdir "%BACKUP_DIR%" >> "%LOG%" 2>&1
robocopy "%TARGET_APP%" "%BACKUP_DIR%\\app" /E /NFL /NDL /NJH /NJS /NC /NS /NP >> "%LOG%" 2>&1
echo [2] robocopy backup errorlevel: %ERRORLEVEL% >> "%LOG%"

REM 3. Apply staged files: staging\\app -> _internal\\app via /MIR
echo [3] applying staging\\app to _internal\\app (MIR)... >> "%LOG%"
robocopy "%STAGING%\\app" "%TARGET_APP%" /MIR /NFL /NDL /NJH /NJS /NC /NS /NP >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo [3] robocopy apply errorlevel: %RC% >> "%LOG%"
REM robocopy returns 0-7 for success (bitmask of changes), 8+ for real failures
if %RC% GEQ 8 (
    echo [3] FAIL -- rolling back >> "%LOG%"
    goto :rollback
)

REM 4. Sanity check: required files must exist
if not exist "%EXE_PATH%" (
    echo [4] FAIL: exe missing -- %EXE_PATH% >> "%LOG%"
    goto :rollback
)
if not exist "%TARGET_APP%\\version.json" (
    echo [4] WARN: version.json missing in target. Continuing anyway. >> "%LOG%"
)
if not exist "%TARGET_APP%\\static\\index.html" (
    echo [4] FAIL: index.html missing -- bad update payload >> "%LOG%"
    goto :rollback
)

REM 5. Mark update success
echo [5] writing success marker (version {target_version}) >> "%LOG%"
> "%LAST_MARKER%" echo {target_version}

REM 6. Launch new version
echo [6] launching new exe >> "%LOG%"
start "" "%EXE_PATH%"
echo [6] launched. exiting helper. >> "%LOG%"
goto :cleanup

:rollback
echo [R] rolling back from backup... >> "%LOG%"
if exist "%BACKUP_DIR%\\app" (
    robocopy "%BACKUP_DIR%\\app" "%TARGET_APP%" /MIR /NFL /NDL /NJH /NJS /NC /NS /NP >> "%LOG%" 2>&1
    echo [R] rollback robocopy errorlevel: %ERRORLEVEL% >> "%LOG%"
) else (
    echo [R] WARN: no backup available -- original files may be in inconsistent state >> "%LOG%"
)
> "%LAST_MARKER%" echo rollback-{target_version}
echo [R] launching old exe (rolled back) >> "%LOG%"
start "" "%EXE_PATH%"
goto :cleanup

:launch_only
REM Pre-flight failed: just relaunch the existing app, no replacement attempted
> "%LAST_MARKER%" echo rollback-{target_version}
echo [LO] launching exe (no changes applied) >> "%LOG%"
start "" "%EXE_PATH%"
goto :cleanup

:cleanup
echo === update_apply.bat END === >> "%LOG%"
REM Self-delete trick (detach via goto, then del current bat)
(goto) 2>nul & del "%~f0"
"""
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text(content, encoding="ascii", newline="\r\n")


# ============================================
# 공개 API
# ============================================
def quick_update_status() -> Dict[str, Any]:
    """현재 빠른 업데이트 가능 환경인지 + 직전 업데이트 결과."""
    last_marker = get_last_update_marker()
    last = None
    last_kind = None
    if last_marker.exists():
        try:
            txt = last_marker.read_text(encoding="utf-8").strip()
            if txt.startswith("rollback-"):
                last_kind = "rollback"
                last = txt[len("rollback-"):]
            else:
                last_kind = "applied"
                last = txt
        except Exception:
            pass
    return {
        "frozen": is_frozen(),
        "supported": is_frozen(),
        "install_dir": str(get_install_dir()) if is_frozen() else None,
        "staging_dir": str(get_staging_dir()),
        "current_version": config.APP_VERSION,
        "last_update_marker": str(last_marker),
        "last_update_version": last,
        "last_update_kind": last_kind,  # 'applied' | 'rollback' | None
    }


def consume_last_update_marker() -> Optional[Dict[str, Any]]:
    """앱 시작 직후 1회 호출. 마커가 있으면 읽고 삭제 후 dict 반환.
    없으면 None. 결과는 frontend 에 토스트로 노출.
    """
    last_marker = get_last_update_marker()
    if not last_marker.exists():
        return None
    try:
        txt = last_marker.read_text(encoding="utf-8").strip()
    except Exception:
        txt = ""
    try:
        last_marker.unlink()
    except Exception:
        pass
    if not txt:
        return None
    if txt.startswith("rollback-"):
        return {"kind": "rollback", "version": txt[len("rollback-"):]}
    return {"kind": "applied", "version": txt}


def perform_quick_update(
    download_url: str,
    expected_version: str,
    expected_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """
    빠른 업데이트 풀 사이클:
     1. zip 다운로드
     2. SHA256 검증 (expected_sha256 가 있을 때만)
     3. manifest 호환성 체크
     4. staging 에 풀기
     5. helper .bat 작성 + 실행
     6. 호출자(앱) 가 자기 종료 트리거 — helper 가 종료 대기 후 교체
    이 함수가 정상 반환하면 helper 는 이미 백그라운드에서 시작됨.
    호출 측은 0.5~1초 후 sys.exit() 또는 webview 창 close 로 앱 종료해야 함.
    """
    if not is_frozen():
        raise RuntimeError(
            "빠른 업데이트는 .exe 로 설치된 앱에서만 작동합니다 (현재 dev 모드)."
        )

    install_dir = get_install_dir()
    if install_dir is None or not install_dir.exists():
        raise RuntimeError("install_dir 를 찾을 수 없습니다.")

    # 1. download
    zip_path = get_zip_download_path(expected_version)
    log.info(f"[quick_update] downloading {download_url} -> {zip_path}")
    size = download_zip(download_url, zip_path)
    log.info(f"[quick_update] downloaded {size:,} bytes")

    # 2. sha256
    if expected_sha256:
        actual = sha256_of(zip_path)
        if actual.lower() != expected_sha256.lower():
            zip_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA256 불일치 — 다운로드 손상.\nexpected: {expected_sha256}\nactual:   {actual}"
            )
        log.info("[quick_update] sha256 OK")

    # 3. manifest 호환성
    manifest = read_manifest_from_zip(zip_path)
    log.info(f"[quick_update] manifest: {manifest}")
    validate_compatibility(manifest, config.APP_VERSION)
    target_version = manifest.get("version") or expected_version

    # 4. staging
    staging = get_staging_dir()
    file_count = extract_to_staging(zip_path, staging)
    log.info(f"[quick_update] extracted {file_count} files to {staging}")

    # 다운받은 zip 은 staging 후엔 불필요
    try:
        zip_path.unlink()
    except Exception:
        pass

    # 5. helper 생성
    helper_path = get_helper_path()
    current_pid = os.getpid()
    write_apply_helper(install_dir, staging, helper_path, target_version, current_pid)
    log.info(f"[quick_update] helper written: {helper_path}")

    # 6. helper 실행 — v2.4.2: shell 의 START 명령 사용 (가장 확실한 detach)
    # 이전 (DETACHED_PROCESS) 은 일부 환경에서 부모 종료 시 같이 죽는 quirk 있음.
    # `start "" /B` 는 cmd 의 빌트인이라 부모 프로세스와 완전 독립.
    try:
        # /B = no new console window (background)
        # 빈 따옴표 "" = title 자리 (start 의 첫 따옴표 인자는 창 제목)
        subprocess.Popen(
            f'start "InterioNote Updater" /B cmd /c "{helper_path}"',
            shell=True,
            cwd=str(config.USER_CACHE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        raise RuntimeError(f"helper 실행 실패: {type(e).__name__}: {e}")

    log.info("[quick_update] helper launched, waiting for app to exit")
    return {
        "ok": True,
        "target_version": target_version,
        "file_count": file_count,
        "manifest": manifest,
        "next": "앱이 곧 종료됩니다. 자동으로 새 버전으로 재시작됩니다.",
    }


def schedule_app_exit(delay_sec: float = 1.0) -> None:
    """별도 스레드에서 잠깐 기다린 뒤 앱 종료. helper 가 종료 대기하다 교체 진행."""
    def _do():
        time.sleep(delay_sec)
        log.info("[quick_update] exiting app for update apply...")
        # pywebview 가 띄운 webview 와 FastAPI 둘 다 종료. 가장 확실한 방법.
        os._exit(0)
    t = threading.Thread(target=_do, daemon=True)
    t.start()
