"""Пароли, сессии, защита от CSRF и ограничение попыток входа.

Решения (зафиксированы в spec/tech/architecture.md):
- пароли — Argon2id (argon2-cffi, параметры RFC 9106 по умолчанию библиотеки);
- сессия — случайный токен 256 бит в cookie HttpOnly + SameSite=Lax; в БД хранится только
  SHA-256 токена, поэтому утечка БД не даёт войти чужой сессией;
- CSRF — проверка заголовков Origin / Sec-Fetch-Site для изменяющих запросов и обязательный
  Content-Type: application/json у запросов с телом (кросс-доменная HTML-форма его не отправит);
- вход — не больше N неудачных попыток на пару email+IP за окно, затем 429.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .errors import ApiError, validation

_hasher = PasswordHasher()
# Хеш для несуществующего email: проверка занимает столько же времени, сколько для настоящего.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PASSWORD_MIN, PASSWORD_MAX = 8, 128


def normalize_email(value) -> str:
    if not isinstance(value, str):
        raise validation("Введите корректный email")
    email = value.strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise validation("Введите корректный email")
    return email


def check_password_policy(value) -> str:
    if not isinstance(value, str):
        raise validation("Не менее 8 символов")
    if len(value) < PASSWORD_MIN:
        raise validation("Не менее 8 символов")
    if len(value) > PASSWORD_MAX:
        raise validation("Не более 128 символов")
    return value


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


# ------------------------------------------------------------------------------- сессии
def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def session_expiry(ttl_hours: int) -> str:
    return iso(utcnow() + timedelta(hours=ttl_hours))


# ------------------------------------------------------------------------------- CSRF
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def check_csrf(method: str, headers, allowed_origins: list[str], own_origin: str) -> None:
    """Отклоняет изменяющий запрос с чужого сайта. Браузеры отправляют Origin для всех
    не-GET запросов fetch; при его отсутствии (старый клиент, curl) смотрим Sec-Fetch-Site."""
    if method not in UNSAFE_METHODS:
        return
    origin = headers.get("origin")
    if origin:
        origin = origin.rstrip("/")
        if origin != own_origin and origin not in allowed_origins:
            raise ApiError(403, "CSRF_FAILED", "Запрос отклонён: недоверенный источник.")
    elif headers.get("sec-fetch-site", "") == "cross-site":
        raise ApiError(403, "CSRF_FAILED", "Запрос отклонён: недоверенный источник.")
    if method != "DELETE":
        ctype = headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise ApiError(400, "VALIDATION_ERROR", "Ожидается JSON (Content-Type: application/json).")


# ------------------------------------------------------------------------------- попытки входа
class LoginLimiter:
    """Счётчик неудачных входов в памяти процесса. При нескольких процессах сервера
    его нужно вынести в общее хранилище; для учебного запуска хватает одного процесса."""

    def __init__(self, max_failures: int, window_minutes: int):
        self.max = max_failures
        self.window = window_minutes * 60
        self._fails: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, q: deque[float], now: float) -> None:
        while q and now - q[0] > self.window:
            q.popleft()

    def check(self, email: str, ip: str) -> None:
        with self._lock:
            q = self._fails[(email, ip)]
            now = time.monotonic()
            self._trim(q, now)
            if len(q) >= self.max:
                retry = int(self.window - (now - q[0])) + 1
                raise ApiError(429, "TOO_MANY_ATTEMPTS",
                               "Слишком много неудачных попыток входа. Повторите позже.",
                               headers={"Retry-After": str(retry)})

    def fail(self, email: str, ip: str) -> None:
        with self._lock:
            self._fails[(email, ip)].append(time.monotonic())

    def success(self, email: str, ip: str) -> None:
        with self._lock:
            self._fails.pop((email, ip), None)
