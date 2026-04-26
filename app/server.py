"""
FastAPI 앱 팩토리.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config
from app.db import init_db
from app.api import analyses as analyses_api
from app.api import home as home_api
from app.api import meetings as meetings_api
from app.api import recording as recording_api
from app.api import settings as settings_api
from app.api import streaming as streaming_api


STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    # 1) 사용자 데이터 디렉터리 보장 (Phase 7A)
    config.ensure_dirs()
    # 2) 이전 버전 위치(C:\InterioNote\data\, models_cache\) 에서 자동 마이그레이션
    mig = config.migrate_legacy_data()
    if mig.get("migrated"):
        for m in mig["migrated"]:
            print(f"[migrate] {m}", flush=True)
    if mig.get("errors"):
        for e in mig["errors"]:
            print(f"[migrate:ERROR] {e}", flush=True)
    # 3) DB 스키마 보장
    init_db()
    # 4) Phase 6A 설정값 보호 — 기존 CLIENT_ROOT 를 settings 에 저장
    config.persist_client_root_default()

    app = FastAPI(title="InterioNote", version="2.0.0")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(STATIC_DIR))

    # Routers
    app.include_router(home_api.router)
    app.include_router(meetings_api.router)
    app.include_router(recording_api.router)
    app.include_router(streaming_api.router)
    app.include_router(analyses_api.router)
    app.include_router(settings_api.router)

    # Pages
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "version": app.version},
        )

    @app.get("/live", response_class=HTMLResponse)
    async def live_page(request: Request):
        return templates.TemplateResponse(
            "live.html",
            {"request": request, "version": app.version},
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        return templates.TemplateResponse(
            "settings.html",
            {"request": request, "version": app.version},
        )

    # Health
    @app.get("/api/health")
    async def health():
        return JSONResponse({"status": "ok", "version": app.version})

    return app
