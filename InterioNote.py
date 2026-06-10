"""
InterioNote - 진입점
내부 FastAPI 서버를 백그라운드 스레드로 기동하고,
pywebview 로 네이티브 앱 창(Edge WebView2)을 연다.

실행:
  - 개발: dev.bat 더블클릭
  - 배포: PyInstaller 로 빌드된 InterioNote.exe 더블클릭 (Phase 6 이후)
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path


# ============================================
# Phase 7B-2 v2: Windows 11 26200+ 대응
# windowed 부트로더(runw.exe)가 silent 차단되는 이슈 때문에
# console=True 로 빌드하되 시작 즉시 console 을 detach 해서
# 작업표시줄에 cmd 창이 남지 않게 함.
# spec 의 hide_console 옵션이 일부 환경에서 minimize 로만 동작하는 보완.
# ============================================
def _detach_console_on_windows() -> None:
    """
    Phase 7B-2 v2 + v2.4.6 fix:
    - hide console window (SW_HIDE)
    - redirect stdout/stderr at OS level (os.dup2) so C extensions like ctranslate2
      that write to raw fd 1/2 don't crash with [Errno 9] Bad file descriptor
    - DO NOT call FreeConsole() — that invalidates fd 1/2 which native code may use
    """
    if os.name != "nt":
        return
    # dev mode: keep cmd attached
    if not getattr(sys, "frozen", False):
        return
    try:
        # v2.5.4: 진짜 해결책 — fd 먼저 redirect → 그 다음 FreeConsole.
        # 이전 시행착오:
        #  - SW_HIDE 만 → 작업표시줄에 minimize 형태로 남음
        #  - WS_EX_TOOLWINDOW + SetWindowPos → 일부 환경에서 여전히 taskbar entry
        #  - FreeConsole 직접 호출 → ctranslate2 가 raw fd 에 쓰면 EBADF
        # 정답: dup2 로 fd 1,2 를 log 파일로 옮긴 뒤 FreeConsole 호출.
        # → console window 자체가 destroy 됨 (taskbar entry 원천 방지).
        # → fd 1,2 는 log 파일 가리키므로 native code 가 써도 안전.

        # Step 1: 로그 파일 열기 + fd 1,2 redirect (FreeConsole 전에)
        try:
            appdata = os.environ.get("APPDATA")
            if appdata:
                log_dir = os.path.join(appdata, "InterioNote")
                os.makedirs(log_dir, exist_ok=True)
                log_path = os.path.join(log_dir, "app.log")
            else:
                log_path = os.devnull

            log_fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.dup2(log_fd, 1)
                os.dup2(log_fd, 2)
            finally:
                try:
                    os.close(log_fd)
                except OSError:
                    pass

            try:
                sys.stdout = os.fdopen(1, "w", encoding="utf-8", buffering=1, closefd=False)
                sys.stderr = os.fdopen(2, "w", encoding="utf-8", buffering=1, closefd=False)
            except Exception:
                pass

            try:
                from datetime import datetime as _dt
                msg = (
                    "\n" + "=" * 60 + "\n"
                    + f"=== InterioNote start: {_dt.now().isoformat(timespec='seconds')} ===\n"
                    + "=" * 60 + "\n"
                )
                sys.stdout.write(msg)
                sys.stdout.flush()
            except Exception:
                pass
        except Exception:
            # log 파일 못 열면 fallback to NUL via dup2 (native fd 안전 보장)
            try:
                nul_fd = os.open(os.devnull, os.O_WRONLY)
                os.dup2(nul_fd, 1)
                os.dup2(nul_fd, 2)
                os.close(nul_fd)
            except Exception:
                pass

        # Step 2: 이제 FreeConsole 안전하게 호출 가능 — fd 1,2 가 console 안 가리킴.
        # FreeConsole 이 console window 를 destroy → taskbar entry 자체가 사라짐.
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32
            # 1) 먼저 hide (FreeConsole 전 잠깐의 시각적 깜빡임 줄임)
            try:
                hwnd = kernel32.GetConsoleWindow()
                if hwnd:
                    user32.ShowWindow(hwnd, 0)  # SW_HIDE
            except Exception:
                pass
            # 2) FreeConsole — process 에서 console 분리 + window destroy
            try:
                kernel32.FreeConsole()
            except Exception:
                pass
        except Exception:
            pass
    except Exception:
        pass


_detach_console_on_windows()


# --- 프로젝트 루트를 import path 에 추가 (dev/pyinstaller 양쪽 대응) ---
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# pywebview / uvicorn 은 아래에서 import (import 순서 중요: 로깅 먼저)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("InterioNote")


def _find_free_port(start: int = 8765, end: int = 8800) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"사용 가능한 포트가 {start}~{end} 범위에 없습니다.")


def _wait_for_server(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _run_server(port: int) -> None:
    """데몬 스레드에서 실행될 서버 루프."""
    import uvicorn

    from app.server import create_app

    fastapi_app = create_app()
    # v3.5.2: host="0.0.0.0" 으로 LAN 노출 (QR 스마트폰 스캔용 + 향후 multi-device 활용)
    # 인증 미들웨어로 보호되며, /print-summary 만 화이트리스트 → 보안 영향 최소
    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()


def main() -> int:
    # --- 1) 포트 확보 ---
    try:
        port = _find_free_port()
    except RuntimeError as e:
        log.error(str(e))
        return 1

    # --- 2) FastAPI 서버 스레드 기동 ---
    log.info(f"서버 시작 중... (port={port})")
    server_thread = threading.Thread(
        target=_run_server, args=(port,), daemon=True, name="fastapi-server"
    )
    server_thread.start()

    if not _wait_for_server(port, timeout=15.0):
        log.error("서버가 15초 내에 시작되지 않았습니다.")
        return 1
    log.info(f"서버 준비 완료: http://127.0.0.1:{port}")

    # --- 3) pywebview 로 네이티브 앱 창 ---
    try:
        import webview
    except ImportError as e:
        log.error(f"pywebview import 실패: {e}")
        log.error("`pip install pywebview` 이 필요합니다.")
        return 1

    from app.config import WINDOW_TITLE, WINDOW_SIZE, WINDOW_MIN_SIZE

    # ----------------------------------------
    # JS Bridge API — settings.html 의 "찾아보기" 버튼이
    # 호출하는 네이티브 폴더 선택 다이얼로그
    # ----------------------------------------
    class JsBridge:
        """
        webview 의 js_api 로 노출. 프론트엔드에서:
          await window.pywebview.api.pick_folder()
        ---
        반환:
          - 사용자가 폴더 선택 시: 절대 경로 문자열
          - 취소 시: 빈 문자열
          - 에러 시: {"error": "메시지"}
        """
        def __init__(self):
            self._window = None

        def set_window(self, w):
            self._window = w

        def pick_folder(self, initial_dir: str = ""):
            try:
                w = self._window
                if w is None:
                    return {"error": "윈도우 핸들이 아직 준비되지 않았습니다."}
                kwargs = {}
                if initial_dir and Path(initial_dir).exists():
                    kwargs["directory"] = initial_dir
                paths = w.create_file_dialog(
                    webview.FOLDER_DIALOG,
                    allow_multiple=False,
                    **kwargs,
                )
                if not paths:
                    return ""  # 취소
                first = paths[0] if isinstance(paths, (list, tuple)) else paths
                return str(first)
            except Exception as e:
                log.error(f"pick_folder 실패: {type(e).__name__}: {e}")
                return {"error": f"{type(e).__name__}: {e}"}

        def pick_file(self, ext: str = "xlsx", initial_dir: str = ""):
            """v2.6.0: xlsx 등 단일 파일 선택 (OJT 연동 마법사용)."""
            try:
                w = self._window
                if w is None:
                    return {"error": "윈도우 핸들이 아직 준비되지 않았습니다."}
                ext = (ext or "xlsx").lstrip(".").lower()
                # 한국어 이름 + 확장자 패턴
                if ext in ("xlsx", "xls", "xlsm"):
                    file_types = ("Excel 파일 (*.xlsx;*.xlsm;*.xls)", "All files (*.*)")
                else:
                    file_types = (f"{ext.upper()} 파일 (*.{ext})", "All files (*.*)")
                kwargs = {"file_types": file_types}
                if initial_dir and Path(initial_dir).exists():
                    kwargs["directory"] = initial_dir
                paths = w.create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=False,
                    **kwargs,
                )
                if not paths:
                    return ""  # 취소
                first = paths[0] if isinstance(paths, (list, tuple)) else paths
                return str(first)
            except Exception as e:
                log.error(f"pick_file 실패: {type(e).__name__}: {e}")
                return {"error": f"{type(e).__name__}: {e}"}

        def pick_audio_file(self, initial_dir: str = ""):
            """v3.5.5: 외부 음성 파일 선택 (mp3 / m4a / wav 등)."""
            try:
                w = self._window
                if w is None:
                    return {"error": "윈도우 핸들이 아직 준비되지 않았습니다."}
                file_types = (
                    "음성 파일 (*.mp3;*.m4a;*.wav;*.ogg;*.opus;*.aac;*.flac;*.webm)",
                    "All files (*.*)",
                )
                kwargs = {"file_types": file_types}
                if initial_dir and Path(initial_dir).exists():
                    kwargs["directory"] = initial_dir
                paths = w.create_file_dialog(
                    webview.OPEN_DIALOG, allow_multiple=False, **kwargs,
                )
                if not paths:
                    return ""
                first = paths[0] if isinstance(paths, (list, tuple)) else paths
                return str(first)
            except Exception as e:
                log.error(f"pick_audio_file 실패: {type(e).__name__}: {e}")
                return {"error": f"{type(e).__name__}: {e}"}

        def open_in_explorer(self, path: str):
            """탐색기에서 폴더 또는 파일 위치 열기 (Phase 7B-3)."""
            try:
                if not path:
                    return {"error": "경로가 비어 있습니다."}
                p = Path(path).expanduser()
                if not p.exists():
                    return {"error": f"경로가 존재하지 않습니다: {p}"}
                import subprocess
                if p.is_dir():
                    subprocess.Popen(["explorer", str(p)])
                else:
                    subprocess.Popen(["explorer", "/select,", str(p)])
                return {"ok": True}
            except Exception as e:
                log.error(f"open_in_explorer 실패: {type(e).__name__}: {e}")
                return {"error": f"{type(e).__name__}: {e}"}

        def open_external_url(self, url: str):
            """기본 브라우저로 URL 열기 (다운로드 페이지 등)."""
            try:
                if not url:
                    return {"error": "URL 이 비어 있습니다."}
                import webbrowser
                webbrowser.open(url, new=2)
                return {"ok": True}
            except Exception as e:
                return {"error": f"{type(e).__name__}: {e}"}

        def get_data_paths(self):
            """사용자 데이터 폴더 경로들 반환 (UI 에서 표시·열기)."""
            try:
                from app import config as _cfg
                return {
                    "user_data_dir": str(_cfg.USER_DATA_DIR),
                    "user_cache_dir": str(_cfg.USER_CACHE_DIR),
                    "db_path": str(_cfg.DB_PATH),
                    "models_cache_dir": str(_cfg.MODELS_CACHE_DIR),
                    "temp_recording_dir": str(_cfg.TEMP_RECORDING_DIR),
                }
            except Exception as e:
                return {"error": f"{type(e).__name__}: {e}"}

    bridge = JsBridge()

    url = f"http://127.0.0.1:{port}"
    window = webview.create_window(
        title=WINDOW_TITLE,
        url=url,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=WINDOW_MIN_SIZE,
        background_color="#F9FAFB",
        resizable=True,
        confirm_close=False,
        js_api=bridge,
    )
    bridge.set_window(window)
    # Windows 11 기본: Edge WebView2 사용 (gui='edgechromium')
    # 명시적으로 지정하면 없는 환경에서 즉시 오류가 떠서 진단이 쉽다.
    webview.start(gui="edgechromium" if os.name == "nt" else None)
    log.info("창이 닫혔습니다. 종료합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
