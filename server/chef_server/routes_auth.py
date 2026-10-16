"""Регистрация, вход, выход, текущий пользователь (AUTH-01, SC-01)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import JSONResponse

from .activity import Trace
from .db import Tx, new_id, now
from .deps import as_object, get_conn, ok, public_user, require_user, rid
from .errors import ApiError, validation
from .security import (check_password_policy, hash_password, needs_rehash, new_session_token,
                       normalize_email, session_expiry, token_hash, verify_password)

router = APIRouter()


def create_account(conn: sqlite3.Connection, email: str, password: str, role: str) -> dict:
    """Создание аккаунта; повторный email (без учёта регистра) — 409 EMAIL_EXISTS."""
    user = {"user_id": new_id(), "email": email, "role": role, "created_at": now()}
    pw_hash = hash_password(password)  # медленный хеш — вне транзакции записи
    with Tx(conn):
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise ApiError(409, "EMAIL_EXISTS", "Этот email уже зарегистрирован.")
        conn.execute("INSERT INTO users(user_id, email, role, password_hash, created_at) VALUES (?,?,?,?,?)",
                     (user["user_id"], email, role, pw_hash, user["created_at"]))
    return user


@router.post("/auth/register", status_code=201)
def register(request: Request, payload=Body(None), conn: sqlite3.Connection = Depends(get_conn)):
    body = as_object(payload)
    if "role" in body:  # публичная регистрация не назначает роль
        raise validation("Самостоятельная регистрация создаёт только пользователя.")
    email = normalize_email(body.get("email"))
    password = check_password_policy(body.get("password"))
    trace = Trace(rid(request))
    user = create_account(conn, email, password, "user")
    trace.skip("LLM")
    request.app.state.activity.record(conn, trace, "register", user["user_id"])
    return ok(request, user)


@router.post("/auth/login")
def login(request: Request, payload=Body(None), conn: sqlite3.Connection = Depends(get_conn)):
    body = as_object(payload)
    email = normalize_email(body.get("email"))
    password = body.get("password")
    if not isinstance(password, str) or not password:
        raise validation("Введите пароль")
    st = request.app.state
    ip = request.client.host if request.client else "?"
    st.limiter.check(email, ip)
    trace = Trace(rid(request))
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not verify_password(row["password_hash"] if row else None, password):
        st.limiter.fail(email, ip)
        trace.skip("LLM")
        st.activity.record(conn, trace, "login", None, status="error")
        raise ApiError(401, "INVALID_CREDENTIALS", "Неверный email или пароль.")
    st.limiter.success(email, ip)
    if needs_rehash(row["password_hash"]):
        conn.execute("UPDATE users SET password_hash = ? WHERE user_id = ?",
                     (hash_password(password), row["user_id"]))
    token = new_session_token()
    t = now()
    s = st.settings
    conn.execute("DELETE FROM sessions WHERE user_id = ? AND expires_at <= ?", (row["user_id"], t))
    conn.execute("INSERT INTO sessions(token_hash, user_id, created_at, last_seen_at, expires_at) VALUES (?,?,?,?,?)",
                 (token_hash(token), row["user_id"], t, t, session_expiry(s.session_ttl_hours)))
    trace.skip("LLM")
    st.activity.record(conn, trace, "login", row["user_id"])
    response = JSONResponse(ok(request, public_user(row)))
    response.set_cookie(s.session_cookie, token, max_age=s.session_ttl_hours * 3600, path="/",
                        httponly=True, samesite="lax", secure=s.cookie_secure)
    return response


@router.get("/auth/me")
def me(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    return ok(request, {"user_id": user.user_id, "email": user.email, "role": user.role,
                        "created_at": user.created_at})


@router.post("/auth/logout", status_code=204)
def logout(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (user.session_hash,))
    trace = Trace(rid(request))
    trace.skip("LLM")
    request.app.state.activity.record(conn, trace, "logout", user.user_id)
    s = request.app.state.settings
    response = Response(status_code=204)
    response.delete_cookie(s.session_cookie, path="/", httponly=True, samesite="lax", secure=s.cookie_secure)
    return response
