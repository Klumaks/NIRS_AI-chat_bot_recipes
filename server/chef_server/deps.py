"""Общие зависимости маршрутов: соединение с БД, текущий пользователь, разбор входных данных."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterator

from fastapi import Request

from .db import connect, now
from .errors import auth_required, forbidden, validation
from .security import iso, parse_iso, token_hash, utcnow


@dataclass
class CurrentUser:
    user_id: str
    email: str
    role: str
    created_at: str
    session_hash: str


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def rid(request: Request) -> str:
    return request.state.request_id


def ok(request: Request, data: dict) -> dict:
    return {**data, "request_id": rid(request)}


def resolve_user(request: Request, conn: sqlite3.Connection) -> CurrentUser | None:
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie)
    if not token:
        return None
    h = token_hash(token)
    row = conn.execute(
        "SELECT s.expires_at, s.last_seen_at, u.user_id, u.email, u.role, u.created_at "
        "FROM sessions s JOIN users u ON u.user_id = s.user_id WHERE s.token_hash = ?", (h,)).fetchone()
    if not row:
        return None
    t = utcnow()
    idle_limit = parse_iso(row["last_seen_at"]) + timedelta(hours=settings.session_idle_hours)
    if parse_iso(row["expires_at"]) <= t or idle_limit <= t:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (h,))
        return None
    if t - parse_iso(row["last_seen_at"]) > timedelta(minutes=5):
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?", (iso(t), h))
    return CurrentUser(row["user_id"], row["email"], row["role"], row["created_at"], h)


def require_user(request: Request, conn: sqlite3.Connection) -> CurrentUser:
    user = resolve_user(request, conn)
    if user is None:
        raise auth_required()
    request.state.user_id = user.user_id
    return user


def require_admin(request: Request, conn: sqlite3.Connection) -> CurrentUser:
    user = require_user(request, conn)
    if user.role != "admin":
        raise forbidden()
    return user


def public_user(row) -> dict:
    return {"user_id": row["user_id"], "email": row["email"], "role": row["role"],
            "created_at": row["created_at"]}


# ---------------------------------------------------------------------------- входные данные
def as_object(payload, message: str = "Некорректный JSON запроса.") -> dict:
    if not isinstance(payload, dict):
        raise validation(message)
    return payload


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


NUTRITION_KEYS = ("kcal", "protein_g", "fat_g", "carbs_g")
FILTER_KEYS = set(NUTRITION_KEYS) | {"max_total_time_minutes"}
LABELS = {"kcal": "Калории, ккал", "protein_g": "Белки, г", "fat_g": "Жиры, г", "carbs_g": "Углеводы, г"}


def parse_filters(raw) -> dict:
    """Правила contracts.md: КБЖУ на 100 г — конечные неотрицательные числа или null,
    минимум не выше максимума, время — положительное целое; лишние поля отклоняются.
    Возвращает нормализованный объект без пустых ограничений."""
    if not isinstance(raw, dict):
        raise validation("Передайте объект filters.")
    unknown = set(raw) - FILTER_KEYS
    if unknown:
        raise validation("Некорректные поля фильтров.")
    out: dict = {}
    for key in NUTRITION_KEYS:
        rng = raw.get(key)
        if rng is None:
            continue
        if not isinstance(rng, dict) or set(rng) - {"min", "max"}:
            raise validation("Некорректные поля фильтров.")
        lo, hi = rng.get("min"), rng.get("max")
        for v in (lo, hi):
            if v is not None and (not _is_number(v) or not math.isfinite(v) or v < 0):
                raise validation(f"{LABELS[key]}: введите неотрицательное число")
        if lo is not None and hi is not None and lo > hi:
            raise validation(f"{LABELS[key]}: минимум больше максимума")
        if lo is not None or hi is not None:
            out[key] = {"min": lo, "max": hi}
    t = raw.get("max_total_time_minutes")
    if t is not None:
        if not _is_number(t) or not math.isfinite(t) or t != int(t) or t <= 0:
            raise validation("Время должно быть положительным целым числом")
        out["max_total_time_minutes"] = int(t)
    return out


def page_params(request: Request) -> tuple[int, int]:
    """limit по умолчанию 50, максимум 100; offset от 0 (как в контракте и моках)."""
    def num(name: str, default: int) -> int:
        try:
            return int(request.query_params.get(name, default))
        except ValueError:
            return default
    limit = max(1, min(100, num("limit", 50) or 50))
    offset = max(0, num("offset", 0))
    return limit, offset


def clean_title(text: str, limit: int = 120) -> str:
    title = " ".join(text.split())
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


__all__ = ["now"]
