"""
v2.7.0 U — 수동 전체 백업 API.

%APPDATA%\\InterioNote\\backups\\YYYYMMDD_HHMMSS\\ 에 zip 생성:
  - data/interionote.db (SQLite DB - WAL 포함)
  - app_log.txt (사용자 환경 로그)
  - ojt_backup/ (이전 OJT 백업)
  - 추가로 settings 의 ojt 매핑·client root 등 핵심 설정을 settings_export.json 으로 dump

고객 폴더 (07_고객정보) 는 OneDrive 동기화되어 있을 가능성 높고 용량 커서 포함 X.
사용자가 별도 OneDrive·외장 백업 활용.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app import config
from app.db import db_cursor

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.post("/run")
def run_backup():
    """전체 백업 zip 생성. 반환: {ok, path, size_bytes, files_count}."""
    backup_root = config.USER_DATA_DIR / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = backup_root / f"InterioNote_backup_{ts}.zip"

    files_count = 0
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            # 1) DB (WAL/SHM 함께)
            db_path = config.DB_PATH
            if db_path.exists():
                zf.write(db_path, arcname=f"data/{db_path.name}")
                files_count += 1
                # WAL/SHM 도 (있으면)
                for suffix in ("-wal", "-shm"):
                    sidecar = db_path.parent / (db_path.name + suffix)
                    if sidecar.exists():
                        zf.write(sidecar, arcname=f"data/{sidecar.name}")
                        files_count += 1

            # 2) 앱 로그
            log_path = config.USER_DATA_DIR / "app.log"
            if log_path.exists() and log_path.stat().st_size > 0:
                zf.write(log_path, arcname="app.log")
                files_count += 1

            # 3) 옛 OJT 백업들 (사용자가 옛 OJT 양식 복원 시)
            ojt_backup_dir = config.USER_DATA_DIR / "ojt_backup"
            if ojt_backup_dir.exists():
                for p in ojt_backup_dir.glob("*.xlsx"):
                    zf.write(p, arcname=f"ojt_backup/{p.name}")
                    files_count += 1

            # 4) 핵심 설정 export (사람이 읽기 쉽게)
            try:
                with db_cursor() as cur:
                    rows = cur.execute("SELECT key, value FROM settings").fetchall()
                    settings_dict = {r["key"]: r["value"] for r in rows}
            except Exception:
                settings_dict = {}
            settings_meta = {
                "exported_at": datetime.now().isoformat(timespec="seconds"),
                "app_version": _read_app_version(),
                "user_data_dir": str(config.USER_DATA_DIR),
                "user_cache_dir": str(config.USER_CACHE_DIR),
                "client_root_setting": settings_dict.get("paths.client_root", ""),
                "settings": settings_dict,
            }
            zf.writestr(
                "settings_export.json",
                json.dumps(settings_meta, ensure_ascii=False, indent=2),
            )
            files_count += 1

            # 5) README
            readme = (
                "InterioNote 사용자 데이터 백업\n"
                "================================\n"
                f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"앱 버전: {_read_app_version()}\n\n"
                "포함 내용:\n"
                "  - data/interionote.db    : 고객·상담·전사·분석 DB\n"
                "  - app.log                : 진단 로그\n"
                "  - ojt_backup/            : OJT 동기화 시 자동 생성된 백업들\n"
                "  - settings_export.json   : 모든 사용자 설정 export\n\n"
                "복원 방법:\n"
                "  1. InterioNote 가 켜져있으면 종료\n"
                "  2. data/interionote.db 를 %APPDATA%\\InterioNote\\data\\ 에 덮어쓰기\n"
                "     (옛 DB 가 있으면 먼저 백업)\n"
                "  3. InterioNote 재시작\n\n"
                "고객 폴더 (07_고객정보) 는 본 백업에 포함되지 않습니다 — \n"
                "OneDrive·외장 등으로 별도 백업해주세요.\n"
            )
            zf.writestr("README.txt", readme)
            files_count += 1
    except PermissionError as e:
        if zip_path.exists():
            try: zip_path.unlink()
            except Exception: pass
        raise HTTPException(
            500,
            "백업 zip 생성 실패 — 다른 프로그램이 InterioNote 데이터 파일을 잡고 있을 가능성. "
            "잠시 후 다시 시도해주세요."
        )
    except Exception as e:
        if zip_path.exists():
            try: zip_path.unlink()
            except Exception: pass
        raise HTTPException(500, f"백업 실패: {type(e).__name__}: {str(e)[:300]}")

    return {
        "ok": True,
        "path": str(zip_path),
        "size_bytes": zip_path.stat().st_size,
        "files_count": files_count,
    }


@router.get("/list")
def list_backups():
    """백업 폴더의 zip 목록 (최신순)."""
    backup_root = config.USER_DATA_DIR / "backups"
    if not backup_root.exists():
        return {"backups": []}
    items = []
    for p in sorted(backup_root.glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        items.append({
            "name": p.name,
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
        })
    return {"backups": items, "backup_root": str(backup_root)}


def _read_app_version() -> str:
    try:
        from app.config import APP_VERSION
        return APP_VERSION
    except Exception:
        return "?"
