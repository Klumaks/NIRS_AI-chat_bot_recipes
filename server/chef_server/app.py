"""Сборка FastAPI-приложения «ИИ-шефа»: маршруты /api/v1, ошибки контракта, request_id, CSRF,
раздача собранного фронтенда с SPA fallback."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .activity import ActivityLog
from .config import Settings
from .db import init_db, new_id
from .errors import ApiError
from .llm import LLMClient
from .routes_admin import router as admin_router
from .routes_auth import router as auth_router
from .routes_chats import router as chats_router
from .routes_rag import router as rag_router
from .search_adapter import SearchService
from .security import LoginLimiter, check_csrf

API_PREFIX = "/api/v1"
log = logging.getLogger("chef")


def _error(request: Request, status: int, code: str, message: str, source_url: str | None = None,
           headers: dict | None = None) -> JSONResponse:
    err = {"code": code, "message": message}
    if source_url:
        err["source_url"] = source_url
    request_id = getattr(request.state, "request_id", None) or new_id()
    return JSONResponse({"request_id": request_id, "error": err}, status_code=status, headers=headers)


def build_llm(s: Settings) -> LLMClient:
    return LLMClient(s.llm_provider, s.llm_base_url, s.llm_api_key, s.llm_model, s.llm_timeout_s,
                     s.llm_temperature, s.llm_json_mode, s.llm_context_chars, s.llm_history_messages)


def create_app(settings: Settings | None = None, search: SearchService | None = None,
               llm: LLMClient | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    search = search or SearchService(settings.search_dir, settings.corpus_path, settings.search_mode,
                                     settings.db_path)
    llm = llm or build_llm(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(settings.db_path)
        if settings.search_preload and not search.ready:
            threading.Thread(target=search.load, name="search-load", daemon=True).start()
        yield

    app = FastAPI(title="ИИ-шеф API", version="1.0.0", lifespan=lifespan,
                  docs_url=API_PREFIX + "/docs", openapi_url=API_PREFIX + "/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.state.search = search
    app.state.llm = llm
    app.state.activity = ActivityLog(settings.activity_retention_days)
    app.state.limiter = LoginLimiter(settings.login_max_failures, settings.login_window_minutes)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = new_id()
        if request.url.path.startswith("/api/"):
            own = f"{request.url.scheme}://{request.headers.get('host', '')}"
            try:
                check_csrf(request.method, request.headers, settings.allowed_origins, own)
            except ApiError as exc:
                return _error(request, exc.status, exc.code, exc.message)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return _error(request, exc.status, exc.code, exc.message, exc.source_url, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        return _error(request, 400, "VALIDATION_ERROR", "Некорректный JSON запроса.")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return _error(request, 404, "NOT_FOUND", "Маршрут API не найден.")
        if exc.status_code == 405:
            return _error(request, 405, "METHOD_NOT_ALLOWED", "Метод не поддерживается для этого маршрута.")
        return _error(request, exc.status_code, "HTTP_ERROR", "Не удалось выполнить запрос.")

    @app.exception_handler(Exception)
    async def internal(request: Request, exc: Exception):
        log.exception("Необработанная ошибка, request_id=%s", getattr(request.state, "request_id", "?"))
        return _error(request, 500, "INTERNAL_ERROR", "Внутренняя ошибка сервера. Повторите позже.")

    for router in (auth_router, chats_router, admin_router, rag_router):
        app.include_router(router, prefix=API_PREFIX)

    @app.get(API_PREFIX + "/health")
    def health(request: Request):
        """Диагностика запуска без секретов: готов ли поиск, какая версия корпуса, настроена ли LLM."""
        return {"status": "ok", "search": search.status,
                "llm": {"configured": llm.configured, "provider": settings.llm_provider,
                        "model": llm.model if llm.configured else None},
                "request_id": request.state.request_id}

    @app.api_route(API_PREFIX + "/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(request: Request, rest: str):
        return _error(request, 404, "NOT_FOUND", "Маршрут API не найден.")

    dist = Path(settings.frontend_dist)
    if settings.serve_frontend and (dist / "index.html").exists():
        root = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            """Статика сборки фронтенда; неизвестные адреса интерфейса — index.html (SPA fallback).
            Пути /api сюда не попадают: они обработаны выше и дают JSON-ошибку."""
            candidate = (root / path).resolve()
            if path and candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app
