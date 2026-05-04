"""
FastAPI 앱 팩토리.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app import config
from app.db import init_db
from app.api import analyses as analyses_api
from app.api import appointments as appointments_api
from app.api import auth as auth_api
from app.api import auth_server as auth_server_api
from app.api import backup as backup_api
from app.api import customer as customer_api
from app.api import export as export_api
from app.api import followup as followup_api
from app.api import home as home_api
from app.api import meetings as meetings_api
from app.api import ojt as ojt_api
from app.api import pdf as pdf_api
from app.api import quick_replies as quick_replies_api
from app.api import quote as quote_api
from app.api import recording as recording_api
from app.api import search as search_api
from app.api import settings as settings_api
from app.api import stats as stats_api
from app.api import streaming as streaming_api
from app.api import users as users_api
from app.services.auth_service import decode_token, ensure_master_user


# ─── 인증 미들웨어 ─────────────────────────────────────────────────────────────
# /api/* 경로 전체를 보호. whitelist 에 있는 경로는 토큰 없이 접근 가능.
_AUTH_WHITELIST = {
    "/api/auth/login",      # 로그인 (인증 불필요, 토큰 발급 endpoint)
    "/api/auth/register",   # 회원가입 신청 (v3.3.0 Phase 5, 인증 불필요)
    "/api/health",          # 상태 체크 (헬스체크)
    "/api/app/info",        # 버전 정보 (로그인 페이지 버전 표시용)
    "/api/app/check-update",  # GitHub 업데이트 확인 (시작 팝업용)
}

# v3.5.3: Auth Server 엔드포인트는 X-Auth-Server-Key 헤더로 인증 (JWT 와 별개).
# 이 PREFIX 의 경로는 JWT 검증 우회. 실제 키 검증은 라우터 안에서 수행.
_AUTH_SERVER_PREFIX = "/api/auth-server/"

# PDF 인쇄 경로는 브라우저가 직접 탐색(window.location.href)하므로
# Authorization 헤더를 전송할 수 없음. 읽기 전용 HTML 출력이므로 인증 예외 처리.
_PRINT_SUFFIXES = ("/print-summary", "/print-transcript")


def _is_print_page(path: str) -> bool:
    return path.endswith(_PRINT_SUFFIXES)


class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            # v3.5.3: Auth Server API 는 X-Auth-Server-Key 로 자체 인증 (JWT 우회)
            if request.url.path.startswith(_AUTH_SERVER_PREFIX):
                return await call_next(request)
            if request.url.path not in _AUTH_WHITELIST and not _is_print_page(request.url.path):
                auth_header = request.headers.get("Authorization", "")
                token = (
                    auth_header[len("Bearer "):].strip()
                    if auth_header.startswith("Bearer ")
                    else ""
                )
                if not token:
                    return JSONResponse(
                        {"detail": "인증이 필요합니다."},
                        status_code=401,
                    )
                payload = decode_token(token)
                if payload is None:
                    return JSONResponse(
                        {"detail": "토큰이 유효하지 않거나 만료되었습니다."},
                        status_code=401,
                    )
                request.state.user = payload
        return await call_next(request)


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
    # 5) v3.0.0 Phase 2: 마스터 계정 자동 생성 (없을 때만)
    ensure_master_user()

    app = FastAPI(title="InterioNote", version="3.5.0")

    # v3.0.0 Phase 2: 인증 미들웨어 등록
    app.add_middleware(_AuthMiddleware)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(STATIC_DIR))

    # Routers
    # v3.0.0 Phase 2: 인증·사용자 관리 (화이트리스트 적용으로 /login 동작)
    app.include_router(auth_api.router)
    app.include_router(users_api.router)
    # v3.5.3: 다른 PC 가 호출하는 Auth Server 엔드포인트 (X-Auth-Server-Key 인증)
    app.include_router(auth_server_api.router)
    app.include_router(home_api.router)
    app.include_router(meetings_api.router)
    app.include_router(recording_api.router)
    app.include_router(streaming_api.router)
    app.include_router(analyses_api.router)
    app.include_router(settings_api.router)
    app.include_router(stats_api.router)
    # v2.6.0
    app.include_router(ojt_api.router)
    app.include_router(pdf_api.router)
    app.include_router(customer_api.router)
    # v2.7.0
    app.include_router(quick_replies_api.router)
    app.include_router(backup_api.router)
    # v2.8.0
    app.include_router(quote_api.router)
    app.include_router(search_api.router)
    # v3.0.0 Phase 3
    app.include_router(followup_api.router)
    # v3.5.0
    app.include_router(appointments_api.router)
    app.include_router(export_api.router)

    # Pages
    # v3.0.0 Phase 2: 로그인 페이지 (인증 불필요)
    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "version": app.version},
        )

    # v3.3.0 Phase 5: 회원가입 페이지 (인증 불필요)
    @app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request):
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "version": app.version},
        )

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

    # v2.5.1 L
    @app.get("/stats", response_class=HTMLResponse)
    async def stats_page(request: Request):
        return templates.TemplateResponse(
            "stats.html",
            {"request": request, "version": app.version},
        )

    # v2.5.1 N
    @app.get("/quick-note", response_class=HTMLResponse)
    async def quick_note_page(request: Request):
        return templates.TemplateResponse(
            "quick_note.html",
            {"request": request, "version": app.version},
        )

    # v2.6.0 EE: 고객 360 뷰
    @app.get("/customer/{client_id}", response_class=HTMLResponse)
    async def customer_view_page(request: Request, client_id: int):
        return templates.TemplateResponse(
            "customer.html",
            {"request": request, "version": app.version, "client_id": client_id},
        )

    # v2.8.0: 통합 검색 페이지
    @app.get("/search", response_class=HTMLResponse)
    async def search_page(request: Request):
        return templates.TemplateResponse(
            "search.html",
            {"request": request, "version": app.version},
        )

    # Health
    @app.get("/api/health")
    async def health():
        return JSONResponse({"status": "ok", "version": app.version})

    return app
