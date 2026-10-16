"""Административные маршруты: аккаунты, журнал, диагностика (ADM-01..03, SC-02, SC-09).
Все маршруты требуют роли admin, проверяемой сервером; чужие чаты здесь недоступны."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Request

from .activity import Trace
from .deps import as_object, get_conn, ok, page_params, public_user, require_admin, rid
from .errors import not_found, validation
from .routes_auth import create_account
from .security import check_password_policy, iso, normalize_email, utcnow

router = APIRouter()


@router.get("/admin/users")
def list_users(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    require_admin(request, conn)
    limit, offset = page_params(request)
    total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    rows = conn.execute("SELECT user_id, email, role, created_at FROM users "
                        "ORDER BY created_at, email LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return ok(request, {"items": [public_user(r) for r in rows], "total": total})


@router.post("/admin/users", status_code=201)
def create_user(request: Request, payload=Body(None), conn: sqlite3.Connection = Depends(get_conn)):
    admin = require_admin(request, conn)
    body = as_object(payload)
    role = body.get("role")
    if role not in ("user", "admin"):
        raise validation("Укажите роль: user или admin.")
    email = normalize_email(body.get("email"))
    password = check_password_policy(body.get("password"))
    trace = Trace(rid(request))
    user = create_account(conn, email, password, role)
    trace.skip("LLM")
    request.app.state.activity.record(conn, trace, "create_user", admin.user_id,
                                      target_user_id=user["user_id"], assigned_role=role)
    return ok(request, user)


def _bound(value: str | None, end: bool) -> str | None:
    """Дата YYYY-MM-DD (из поля формы) или полная отметка ISO 8601. Для даты «по»
    включается весь день в UTC."""
    if not value:
        return None
    try:
        if len(value) == 10:
            d = date.fromisoformat(value)
            dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            return iso(dt + timedelta(days=1) - timedelta(milliseconds=1) if end else dt)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return iso(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
    except ValueError:
        raise validation("Проверьте период.")


@router.get("/admin/activity")
def activity(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    require_admin(request, conn)
    p = request.query_params
    days = request.app.state.settings.activity_retention_days
    start = _bound(p.get("from"), False) or iso(utcnow() - timedelta(days=days))
    end = _bound(p.get("to"), True) or iso(utcnow())
    if start > end:
        raise validation("Проверьте период.")
    where, args = "occurred_at >= ? AND occurred_at <= ?", [start, end]
    if p.get("user_id"):
        where += " AND user_id = ?"
        args.append(p.get("user_id"))
    limit, offset = page_params(request)
    total = conn.execute(f"SELECT COUNT(*) FROM events WHERE {where}", args).fetchone()[0]
    rows = conn.execute(f"SELECT * FROM events WHERE {where} ORDER BY occurred_at DESC, id DESC "
                        "LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    items = []
    for r in rows:
        item = {k: r[k] for k in ("occurred_at", "user_id", "event_type", "status", "duration_ms", "request_id")}
        if r["target_user_id"]:
            item["target_user_id"] = r["target_user_id"]
            item["assigned_role"] = r["assigned_role"]
        for key in ("recipe_id", "count", "corpus_version"):  # операции каталога RAG
            if r[key] is not None:
                item[key] = r[key]
        items.append(item)
    return ok(request, {"items": items, "total": total})


@router.get("/admin/requests/{request_id}")
def diagnostic(request_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    require_admin(request, conn)
    row = conn.execute("SELECT data_json FROM diagnostics WHERE request_id = ?", (request_id,)).fetchone()
    if not row:
        raise not_found("Диагностика не найдена.")
    data = json.loads(row["data_json"])
    # request_id диагностики — исследуемого запроса; request_id этого ответа не перезаписывает его
    return {**data, "request_id": data["request_id"]}
