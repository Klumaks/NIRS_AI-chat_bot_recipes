"""Доступ, роли, сессии, CSRF, администрирование (SC-01, SC-02, SC-09; AUTH-01/02, ADM-01/02/03)."""
from __future__ import annotations

from conftest import db_dump

from chef_server.db import connect


def test_register_creates_only_user_and_rejects_role(client_factory):
    api = client_factory()
    r = api.post("/auth/register", {"email": "  Anna@Mail.RU ", "password": "Password123"})
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "user" and body["email"] == "anna@mail.ru" and body["request_id"]
    assert "password" not in body and "password_hash" not in body
    r = api.post("/auth/register", {"email": "boss@mail.ru", "password": "Password123", "role": "admin"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = api.post("/auth/register", {"email": "anna@mail.ru", "password": "Password123"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_EXISTS"
    assert api.post("/auth/register", {"email": "bad", "password": "Password123"}).status_code == 400
    assert api.post("/auth/register", {"email": "x@y.ru", "password": "short"}).status_code == 400
    assert api.post("/auth/register", {"email": "x@y.ru", "password": "p" * 129}).status_code == 400
    # регистрация не входит автоматически
    assert api.get("/auth/me").status_code == 401


def test_login_cookie_me_logout(client_factory):
    api = client_factory()
    api.post("/auth/register", {"email": "u@test.ru", "password": "Password123"})
    r = api.post("/auth/login", {"email": "u@test.ru", "password": "wrong-pass"})
    assert r.status_code == 401
    assert r.json()["error"] == {"code": "INVALID_CREDENTIALS", "message": "Неверный email или пароль."}
    r = api.post("/auth/login", {"email": "nobody@test.ru", "password": "wrong-pass"})
    assert r.json()["error"]["message"] == "Неверный email или пароль."  # одинаковое сообщение
    r = api.post("/auth/login", {"email": "U@TEST.RU", "password": "Password123"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert api.get("/auth/me").json()["email"] == "u@test.ru"
    r = api.post("/auth/logout")
    assert r.status_code == 204 and r.content == b""
    assert api.get("/auth/me").json()["error"]["code"] == "AUTH_REQUIRED"
    assert api.get("/chats").status_code == 401


def test_session_token_not_stored_in_db_and_expiry(client_factory, settings):
    api = client_factory()
    api.register_login("exp@test.ru")
    token = api.c.cookies.get("chef_session")
    conn = connect(settings.db_path)
    rows = [dict(r) for r in conn.execute("SELECT * FROM sessions")]
    assert rows and token not in str(rows)  # хранится только хеш
    conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00.000Z'")
    conn.close()
    assert api.get("/auth/me").status_code == 401
    assert api.post("/selections", {"products_text": "курица"}).status_code == 401


def test_idle_session_expires(client_factory, settings):
    api = client_factory()
    api.register_login("idle@test.ru")
    conn = connect(settings.db_path)
    conn.execute("UPDATE sessions SET last_seen_at = '2000-01-01T00:00:00.000Z'")
    conn.close()
    assert api.get("/auth/me").status_code == 401


def test_login_rate_limit(client_factory):
    api = client_factory()
    api.post("/auth/register", {"email": "rl@test.ru", "password": "Password123"})
    for _ in range(5):
        assert api.post("/auth/login", {"email": "rl@test.ru", "password": "nope-nope"}).status_code == 401
    r = api.post("/auth/login", {"email": "rl@test.ru", "password": "Password123"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert int(r.headers["retry-after"]) > 0


def test_csrf_protection(client_factory):
    api = client_factory()
    api.register_login("csrf@test.ru")
    evil = {"Origin": "https://evil.example"}
    r = api.c.post("/api/v1/selections", json={"products_text": "курица"}, headers=evil)
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_FAILED"
    r = api.c.delete("/api/v1/chats/x", headers=evil)
    assert r.status_code == 403
    r = api.c.post("/api/v1/auth/logout", content="a=1",
                   headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://localhost:5173"})
    assert r.status_code == 400  # не-JSON тело не принимается
    r = api.c.post("/api/v1/selections", json={"products_text": "курица"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert api.get("/auth/me").status_code == 200  # сессия цела


def test_roles_and_admin_user_creation(client_factory, make_admin):
    email, pw = make_admin()
    user = client_factory()
    user.register_login("plain@test.ru")
    assert user.get("/admin/users").json()["error"]["code"] == "FORBIDDEN"
    for role in ("user", "admin"):
        r = user.post("/admin/users", {"email": f"x-{role}@test.ru", "password": "Password123", "role": role})
        assert r.status_code == 403
    assert user.get("/admin/activity").status_code == 403
    assert user.get("/admin/requests/anything").status_code == 403

    admin = client_factory()
    assert admin.post("/auth/login", {"email": email, "password": pw}).status_code == 200
    r = admin.post("/admin/users", {"email": "new-user@test.ru", "password": "Password123", "role": "user"})
    assert r.status_code == 201 and r.json()["role"] == "user"
    r = admin.post("/admin/users", {"email": "new-admin@test.ru", "password": "Password123", "role": "admin"})
    assert r.status_code == 201 and r.json()["role"] == "admin"
    assert admin.post("/admin/users", {"email": "z@test.ru", "password": "Password123", "role": "owner"}).status_code == 400
    assert admin.post("/admin/users", {"email": "z@test.ru", "password": "Password123"}).status_code == 400
    assert admin.post("/admin/users", {"email": "NEW-USER@test.ru", "password": "Password123", "role": "user"}
                      ).json()["error"]["code"] == "EMAIL_EXISTS"
    listing = admin.get("/admin/users").json()
    assert listing["total"] == 4 and "password" not in str(listing) and "argon2" not in str(listing)

    # созданный администратор получает права и сам создаёт обе роли
    second = client_factory()
    assert second.post("/auth/login", {"email": "new-admin@test.ru", "password": "Password123"}).status_code == 200
    for role in ("user", "admin"):
        assert second.post("/admin/users", {"email": f"by2-{role}@test.ru", "password": "Password123",
                                            "role": role}).status_code == 201

    events = admin.get("/admin/activity").json()["items"]
    created = [e for e in events if e["event_type"] == "create_user"]
    assert {e["assigned_role"] for e in created} == {"user", "admin"}
    assert all(e.get("target_user_id") for e in created)


def test_activity_filters_and_diagnostics(client_factory, make_admin, settings):
    email, pw = make_admin()
    admin = client_factory()
    me = admin.post("/auth/login", {"email": email, "password": pw}).json()
    r = admin.post("/selections", {"products_text": "Курица и рис"})
    assert r.status_code == 201
    rid = r.json()["request_id"]
    acts = admin.get("/admin/activity?user_id=" + me["user_id"]).json()
    assert acts["total"] >= 2 and {e["event_type"] for e in acts["items"]} >= {"login", "search"}
    assert all(e["user_id"] == me["user_id"] for e in acts["items"])
    assert admin.get("/admin/activity?from=2001-01-01&to=2001-01-02").json()["total"] == 0
    assert admin.get("/admin/activity?from=2030-01-02&to=2030-01-01").status_code == 400
    assert admin.get("/admin/activity?from=garbage").status_code == 400
    d = admin.get("/admin/requests/" + rid).json()
    assert d["request_id"] == rid and d["corpus_version"] == "test-corpus-v1"
    assert d["normalization_mode"] == "lemma" and d["candidate_ids"]
    llm = [s for s in d["stages"] if s["name"] == "LLM"]
    assert llm == [{"name": "LLM", "status": "not_run", "duration_ms": None}] and d["llm_called"] is False
    assert admin.get("/admin/requests/unknown").status_code == 404
    assert "Курица и рис" not in db_dump(settings)


def test_activity_retention_30_days(client_factory, make_admin, settings, app):
    email, pw = make_admin()
    admin = client_factory()
    admin.post("/auth/login", {"email": email, "password": pw})
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO events(occurred_at, user_id, event_type, status, duration_ms, request_id) "
                 "VALUES ('2000-01-01T00:00:00.000Z', NULL, 'login', 'ok', 1, 'old-req')")
    conn.execute("INSERT INTO diagnostics(request_id, created_at, data_json) VALUES ('old-req', '2000-01-01T00:00:00.000Z', '{}')")
    app.state.activity.purge(conn, force=True)
    assert conn.execute("SELECT COUNT(*) FROM events WHERE request_id='old-req'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM diagnostics WHERE request_id='old-req'").fetchone()[0] == 0
    conn.close()


def test_error_format_and_unknown_route(client_factory):
    api = client_factory()
    r = api.get("/no-such-route")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND" and r.json()["request_id"]
    r = api.c.post("/api/v1/auth/login", content="{not json", headers={"Content-Type": "application/json",
                                                                        "Origin": "http://localhost:5173"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "Traceback" not in r.text
