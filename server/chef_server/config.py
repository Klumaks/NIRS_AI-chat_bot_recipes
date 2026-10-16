"""Настройки сервера «ИИ-шефа».

Все параметры задаются переменными окружения с префиксом CHEF_ (или файлом server/.env,
см. .env.example). Секреты (ключ LLM) читаются только отсюда и никогда не попадают
в ответы API, журнал активности и Git.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Минимальный разбор KEY=VALUE без внешних зависимостей. Окружение важнее файла."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return default if v in (None, "") else int(v)


def _list(name: str, default: list[str]) -> list[str]:
    v = os.environ.get(name)
    return default if v is None else [x.strip().rstrip("/") for x in v.split(",") if x.strip()]


@dataclass
class Settings:
    # Хранилище
    db_path: Path = SERVER_DIR / "data" / "chef.sqlite3"

    # Сессии и защита
    session_cookie: str = "chef_session"
    session_ttl_hours: int = 24 * 7          # абсолютное время жизни сессии
    session_idle_hours: int = 24             # без активности дольше — повторный вход
    cookie_secure: bool = False              # true при HTTPS
    allowed_origins: list[str] = field(default_factory=lambda: [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:8000", "http://127.0.0.1:8000",
    ])
    login_max_failures: int = 5              # неудачных входов на email+IP
    login_window_minutes: int = 15
    activity_retention_days: int = 30

    # Поиск (модуль search/ Александры; сервер его не меняет)
    search_dir: Path = REPO_DIR / "search"
    corpus_path: Path | None = None          # None — data/corpus.jsonl, иначе выборка
    search_mode: str = "lemma"               # lemma | stem | none (при отсутствии pymorphy3 — stem)
    search_preload: bool = True              # грузить индекс при старте, а не на первом запросе

    # LLM (OpenAI-совместимый Chat Completions: Ollama, OpenRouter, YandexGPT, vLLM, …)
    llm_provider: str = "none"               # openai_compatible | none
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_s: int = 60
    llm_temperature: float = 0.2
    llm_json_mode: bool = True               # response_format=json_object, если провайдер умеет
    llm_history_messages: int = 10           # сколько последних сообщений ветки передавать
    llm_context_chars: int = 12000           # бюджет промпта; старые сообщения отбрасываются первыми

    # Раздача собранного фронтенда (frontend/dist) с SPA fallback
    frontend_dist: Path = REPO_DIR / "frontend" / "dist"
    serve_frontend: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(SERVER_DIR / ".env")
        s = cls()
        e = os.environ.get
        if e("CHEF_DB_PATH"):
            s.db_path = Path(e("CHEF_DB_PATH"))
        s.session_ttl_hours = _int("CHEF_SESSION_TTL_HOURS", s.session_ttl_hours)
        s.session_idle_hours = _int("CHEF_SESSION_IDLE_HOURS", s.session_idle_hours)
        s.cookie_secure = _bool("CHEF_COOKIE_SECURE", s.cookie_secure)
        s.allowed_origins = _list("CHEF_ALLOWED_ORIGINS", s.allowed_origins)
        s.login_max_failures = _int("CHEF_LOGIN_MAX_FAILURES", s.login_max_failures)
        s.login_window_minutes = _int("CHEF_LOGIN_WINDOW_MINUTES", s.login_window_minutes)
        s.activity_retention_days = _int("CHEF_ACTIVITY_RETENTION_DAYS", s.activity_retention_days)
        if e("CHEF_SEARCH_DIR"):
            s.search_dir = Path(e("CHEF_SEARCH_DIR"))
        if e("CHEF_CORPUS_PATH"):
            s.corpus_path = Path(e("CHEF_CORPUS_PATH"))
        s.search_mode = e("CHEF_SEARCH_MODE", s.search_mode)
        s.search_preload = _bool("CHEF_SEARCH_PRELOAD", s.search_preload)
        s.llm_provider = e("CHEF_LLM_PROVIDER", s.llm_provider)
        s.llm_base_url = e("CHEF_LLM_BASE_URL", s.llm_base_url).rstrip("/")
        s.llm_api_key = e("CHEF_LLM_API_KEY", s.llm_api_key)
        s.llm_model = e("CHEF_LLM_MODEL", s.llm_model)
        s.llm_timeout_s = _int("CHEF_LLM_TIMEOUT_S", s.llm_timeout_s)
        s.llm_temperature = float(e("CHEF_LLM_TEMPERATURE", s.llm_temperature))
        s.llm_json_mode = _bool("CHEF_LLM_JSON_MODE", s.llm_json_mode)
        s.llm_history_messages = _int("CHEF_LLM_HISTORY_MESSAGES", s.llm_history_messages)
        s.llm_context_chars = _int("CHEF_LLM_CONTEXT_CHARS", s.llm_context_chars)
        if e("CHEF_FRONTEND_DIST"):
            s.frontend_dist = Path(e("CHEF_FRONTEND_DIST"))
        s.serve_frontend = _bool("CHEF_SERVE_FRONTEND", s.serve_frontend)
        return s
