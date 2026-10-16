"""Подбор, фильтры, выбор рецепта, вопросы к LLM и личная история чатов.

Путь запроса: интерфейс → сервер (сессия, владелец) → BM25 (search/rag) → карточки →
выбор рецепта → снимок рецепта в БД → вопрос → LLM по снимку и активной ветке → ответ.
Карточки и рецепт берутся из данных корпуса; LLM вызывается только для вопросов.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Body, Depends, Request, Response

from .activity import Trace
from .db import Tx, dumps, new_id, now
from .deps import (CurrentUser, as_object, clean_title, get_conn, ok, page_params, parse_filters,
                   require_user, rid)
from .errors import ApiError, llm_unavailable, not_found, validation
from .catalog import pack_ids, unpack_ids
from .llm import LLMUnavailable

router = APIRouter()

MAX_TEXT = 2000


# ------------------------------------------------------------------------------ помощники
def _owned_selection(conn, user: CurrentUser, selection_id: str):
    row = conn.execute(
        "SELECT s.*, c.products_text, c.user_id FROM selections s JOIN chats c ON c.chat_id = s.chat_id "
        "WHERE s.selection_id = ? AND c.user_id = ?", (selection_id, user.user_id)).fetchone()
    if not row:
        raise not_found("Подбор не найден или недоступен.")
    return row


def _selection_payload(row, request_id: str | None = None) -> dict:
    return {"chat_id": row["chat_id"], "selection_id": row["selection_id"],
            "corpus_version": row["corpus_version"], "filters": json.loads(row["filters_json"]),
            "items": json.loads(row["items_json"]), "total": row["total"],
            "request_id": request_id or row["request_id"]}


def _search_trace(trace: Trace, search, version: str | None = None) -> None:
    trace.info.update(corpus_version=version or search.corpus_version, index_version=search.index_version,
                      normalization_mode=search.mode)


def _fail(request: Request, conn, trace: Trace, event: str, user_id: str, exc: ApiError):
    trace.info["error_code"] = exc.code
    if not any(s["name"] == "LLM" for s in trace.stages):
        trace.skip("LLM")
    request.app.state.activity.record(conn, trace, event, user_id, status="error")
    raise exc


def _summary_text(total: int, filtered: bool) -> str:
    if total == 0:
        return ("Под эти ограничения ничего не подошло. Попробуйте сбросить фильтры." if filtered else
                "Не нашёл рецептов с этими продуктами. Попробуйте перечислить продукты иначе.")
    return (f"Нашёл {total} подходящих рецептов, показываю первые пять. "
            "В карточках видно, чего не хватает.")


def _snapshot(request: Request, conn, trace: Trace, user_id: str, sel, event: str):
    """Снимок кандидатов подбора; подбор на другой базе корпуса продолжить нельзя."""
    search = request.app.state.search
    cat = search.cat
    if not sel["candidates"] or sel["base_key"] != cat.base_key:
        _fail(request, conn, trace, event, user_id,
              ApiError(409, "RECIPE_UNAVAILABLE", "Подбор сделан на прежней версии корпуса. Начните новый подбор."))
    return unpack_ids(sel["candidates"])


# ------------------------------------------------------------------------------ подбор
@router.post("/selections", status_code=201)
def create_selection(request: Request, payload=Body(None), conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    body = as_object(payload)
    text = body.get("products_text")
    text = text.strip() if isinstance(text, str) else ""
    if not text or len(text) > MAX_TEXT:
        raise validation("Перечислите продукты (до 2000 символов).")
    search = request.app.state.search
    trace = Trace(rid(request))
    try:
        with trace.stage("Предобработка и BM25 по каталогу"):
            ids, revision, tokens = search.candidates(text)
        _search_trace(trace, search)
        if not tokens:
            raise validation("Перечислите продукты (до 2000 символов).")
        with trace.stage("Фильтры, «Не хватает» и карточки"):
            items, total = search.page(ids, revision, tokens, {})
    except ApiError as exc:
        if exc.status == 400:
            raise
        _fail(request, conn, trace, "search", user.user_id, exc)
    trace.skip("Проверенный набор (ещё не подготовлен)")
    trace.info["candidate_ids"] = [i["recipe_id"] for i in items]
    cat = search.cat
    version = cat.version_of(revision)
    trace.info["corpus_version"] = version
    chat_id, selection_id, t = new_id(), new_id(), now()
    with trace.stage("Сохранение чата и снимка кандидатов"):
        with Tx(conn):
            conn.execute("INSERT INTO chats(chat_id, user_id, title, products_text, created_at, updated_at) "
                         "VALUES (?,?,?,?,?,?)", (chat_id, user.user_id, clean_title(text), text, t, t))
            conn.execute("INSERT INTO selections(selection_id, chat_id, corpus_version, filters_json, items_json,"
                         " total, request_id, created_at, updated_at, base_key, catalog_revision, candidates)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (selection_id, chat_id, version, "{}", dumps(items), total, rid(request), t, t,
                          cat.base_key, revision, pack_ids(ids)))
            for role, msg in (("user", text), ("assistant", _summary_text(total, False))):
                conn.execute("INSERT INTO messages(message_id, chat_id, role, text, created_at) VALUES (?,?,?,?,?)",
                             (new_id(), chat_id, role, msg, now()))
    trace.skip("LLM")
    request.app.state.activity.record(conn, trace, "search", user.user_id)
    return {"chat_id": chat_id, "selection_id": selection_id, "corpus_version": version,
            "filters": {}, "items": items, "total": total, "request_id": rid(request)}


@router.post("/selections/{selection_id}/filter")
def filter_selection(selection_id: str, request: Request, payload=Body(None),
                     conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    body = as_object(payload)
    if "filters" not in body:
        raise validation("Передайте объект filters.")
    filters = parse_filters(body["filters"])
    sel = _owned_selection(conn, user, selection_id)
    search = request.app.state.search
    trace = Trace(rid(request))
    try:
        _search_trace(trace, search, sel["corpus_version"])
        ids = _snapshot(request, conn, trace, user.user_id, sel, "filter")
        with trace.stage("Фильтры КБЖУ/времени по всему подбору"):
            items, total = search.page(ids, sel["catalog_revision"], search.query_terms(sel["products_text"]), filters)
    except ApiError as exc:
        if exc.status in (400, 409):
            raise
        _fail(request, conn, trace, "filter", user.user_id, exc)
    trace.info["candidate_ids"] = [i["recipe_id"] for i in items]
    t = now()
    with trace.stage("Сохранение фильтров"):
        with Tx(conn):
            # Чат могли удалить, пока шла фильтрация: запоздалый ответ не восстанавливает его.
            _owned_selection(conn, user, selection_id)
            conn.execute("UPDATE selections SET filters_json = ?, items_json = ?, total = ?, request_id = ?,"
                         " updated_at = ? WHERE selection_id = ?",
                         (dumps(filters), dumps(items), total, rid(request), t, selection_id))
            conn.execute("UPDATE chats SET updated_at = ? WHERE chat_id = ?", (t, sel["chat_id"]))
    trace.skip("LLM")
    request.app.state.activity.record(conn, trace, "filter", user.user_id)
    return {"chat_id": sel["chat_id"], "selection_id": selection_id, "corpus_version": sel["corpus_version"],
            "filters": filters, "items": items, "total": total, "request_id": rid(request)}


@router.post("/selections/{selection_id}/recipe")
def select_recipe(selection_id: str, request: Request, payload=Body(None),
                  conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    body = as_object(payload)
    recipe_id = body.get("recipe_id")
    if not isinstance(recipe_id, int) or isinstance(recipe_id, bool):
        raise validation("Укажите recipe_id — целое число.")
    sel = _owned_selection(conn, user, selection_id)
    shown = {i["recipe_id"]: i for i in json.loads(sel["items_json"])}
    if recipe_id not in shown:
        raise not_found("Рецепт не найден в этом подборе.")
    search = request.app.state.search
    trace = Trace(rid(request))
    trace.info["selected_recipe_id"] = recipe_id
    _search_trace(trace, search, sel["corpus_version"])
    try:
        _snapshot(request, conn, trace, user.user_id, sel, "select_recipe")
        with trace.stage("Полный рецепт версии подбора"):
            full = search.full_recipe(recipe_id, sel["catalog_revision"])
    except ApiError as exc:
        if exc.status == 409:
            raise
        _fail(request, conn, trace, "select_recipe", user.user_id, exc)
    if full is None or full["url"] != shown[recipe_id]["url"]:
        _fail(request, conn, trace, "select_recipe", user.user_id,
              ApiError(409, "RECIPE_UNAVAILABLE", "Рецепт недоступен в версии этого подбора. Начните новый подбор."))
    if not full["steps"]:
        _fail(request, conn, trace, "select_recipe", user.user_id,
              ApiError(409, "RECIPE_INCOMPLETE", "В источнике нет шагов приготовления этого рецепта.",
                       source_url=full["url"]))
    full["missing_ingredients"] = shown[recipe_id]["missing_ingredients"]
    conversation_id, t = new_id(), now()
    with trace.stage("Снимок рецепта и новая ветка вопросов"):
        with Tx(conn):
            _owned_selection(conn, user, selection_id)
            conn.execute("INSERT INTO conversations(conversation_id, chat_id, recipe_id, corpus_version, recipe_json,"
                         " created_at) VALUES (?,?,?,?,?,?)",
                         (conversation_id, sel["chat_id"], recipe_id, full["corpus_version"], dumps(full), t))
            conn.execute("UPDATE chats SET active_conversation_id = ?, updated_at = ? WHERE chat_id = ?",
                         (conversation_id, t, sel["chat_id"]))
            conn.execute("INSERT INTO messages(message_id, chat_id, conversation_id, role, text, recipe_id, created_at)"
                         " VALUES (?,?,?,?,?,?,?)",
                         (new_id(), sel["chat_id"], conversation_id, "assistant",
                          f"Выбран рецепт «{full['title']}». Можно задавать вопросы по его шагам.", recipe_id, t))
    trace.skip("LLM")
    request.app.state.activity.record(conn, trace, "select_recipe", user.user_id)
    return {**full, "chat_id": sel["chat_id"], "conversation_id": conversation_id, "request_id": rid(request)}


# ------------------------------------------------------------------------------ вопросы
def _answer_payload(chat_id: str, message_id: str, row) -> dict:
    return {"chat_id": chat_id, "message_id": message_id, "answer": row["text"],
            "sources": json.loads(row["sources_json"] or "[]"), "status": row["status"] or "answered"}


def _existing_answer(conn, chat_id: str, conversation_id: str, message_id: str):
    q = conn.execute("SELECT conversation_id, role FROM messages WHERE chat_id = ? AND message_id = ?",
                     (chat_id, message_id)).fetchone()
    if not q:
        return None
    if q["conversation_id"] != conversation_id or q["role"] != "user":
        raise validation("Этот message_id уже использован для другого сообщения.")
    return conn.execute("SELECT * FROM messages WHERE chat_id = ? AND reply_to = ? AND role = 'assistant'",
                        (chat_id, message_id)).fetchone()


@router.post("/conversations/{conversation_id}/messages")
def ask(conversation_id: str, request: Request, payload=Body(None), conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    body = as_object(payload)
    text, message_id = body.get("text"), body.get("message_id")
    if (not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT
            or not isinstance(message_id, str) or not (0 < len(message_id) <= 100)):
        raise validation("Укажите вопрос (до 2000 символов) и message_id.")
    text = text.strip()
    conv = conn.execute(
        "SELECT v.*, c.active_conversation_id FROM conversations v JOIN chats c ON c.chat_id = v.chat_id "
        "WHERE v.conversation_id = ? AND c.user_id = ?", (conversation_id, user.user_id)).fetchone()
    if not conv:
        raise not_found("Диалог не найден или недоступен.")
    chat_id = conv["chat_id"]
    existing = _existing_answer(conn, chat_id, conversation_id, message_id)
    if existing:  # повтор того же вопроса: без второго экземпляра сообщения
        return ok(request, _answer_payload(chat_id, message_id, existing))

    st = request.app.state
    recipe = json.loads(conv["recipe_json"])
    trace = Trace(rid(request))
    trace.info.update(selected_recipe_id=conv["recipe_id"], corpus_version=conv["corpus_version"],
                      index_version=None, normalization_mode=None)  # вопрос использует снимок, не индекс
    if conv["active_conversation_id"] != conversation_id:
        _fail(request, conn, trace, "question", user.user_id,
              ApiError(409, "RECIPE_UNAVAILABLE", "Выбрано другое блюдо: вопросы задаются по текущему рецепту."))
    if not recipe.get("steps"):  # снимок без шагов продолжать нельзя (не создаётся сервером)
        _fail(request, conn, trace, "question", user.user_id,
              ApiError(409, "RECIPE_UNAVAILABLE",
                       "Сохранённый рецепт доступен только для чтения. Начните новый подбор."))
    with trace.stage("Контекст выбранного рецепта и ветки"):
        history = [{"role": r["role"], "text": r["text"]} for r in conn.execute(
            "SELECT role, text FROM messages WHERE conversation_id = ? AND (role = 'user' OR reply_to IS NOT NULL)"
            " ORDER BY seq", (conversation_id,))]
    llm = st.llm
    trace.info["model"] = llm.model_label
    try:
        with trace.stage("LLM"):
            trace.info["llm_called"] = llm.configured
            result = llm.answer(recipe, history, text)
    except LLMUnavailable as exc:
        trace.info["error_code"] = f"LLM_UNAVAILABLE:{exc.code}"
        st.activity.record(conn, trace, "question", user.user_id, status="error")
        raise llm_unavailable()
    sources = ([{"recipe_id": recipe["recipe_id"], "url": recipe["url"], "step_numbers": result.step_numbers}]
               if result.status == "answered" else [])
    t = now()
    with trace.stage("Сохранение вопроса и ответа"):
        with Tx(conn):
            alive = conn.execute("SELECT 1 FROM conversations v JOIN chats c ON c.chat_id = v.chat_id "
                                 "WHERE v.conversation_id = ? AND c.user_id = ?",
                                 (conversation_id, user.user_id)).fetchone()
            if not alive:  # чат удалён во время ответа модели — не создаём его заново
                raise not_found("Диалог не найден или недоступен.")
            again = _existing_answer(conn, chat_id, conversation_id, message_id)
            if again:
                return ok(request, _answer_payload(chat_id, message_id, again))
            conn.execute("INSERT INTO messages(message_id, chat_id, conversation_id, role, text, recipe_id, created_at)"
                         " VALUES (?,?,?,?,?,?,?)",
                         (message_id, chat_id, conversation_id, "user", text, recipe["recipe_id"], t))
            conn.execute("INSERT INTO messages(message_id, chat_id, conversation_id, role, text, recipe_id,"
                         " sources_json, status, reply_to, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (new_id(), chat_id, conversation_id, "assistant", result.answer, recipe["recipe_id"],
                          dumps(sources), result.status, message_id, now()))
            conn.execute("UPDATE chats SET updated_at = ? WHERE chat_id = ?", (t, chat_id))
    st.activity.record(conn, trace, "question", user.user_id)
    return ok(request, {"chat_id": chat_id, "message_id": message_id, "answer": result.answer,
                        "sources": sources, "status": result.status})


# ------------------------------------------------------------------------------ история
@router.get("/chats")
def list_chats(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    limit, offset = page_params(request)
    total = conn.execute("SELECT COUNT(*) FROM chats WHERE user_id = ?", (user.user_id,)).fetchone()[0]
    rows = conn.execute("SELECT chat_id, title, created_at, updated_at FROM chats WHERE user_id = ? "
                        "ORDER BY updated_at DESC, created_at DESC LIMIT ? OFFSET ?",
                        (user.user_id, limit, offset)).fetchall()
    return ok(request, {"items": [dict(r) for r in rows], "total": total})


def _message(r) -> dict:
    m = {"message_id": r["message_id"], "role": r["role"], "text": r["text"], "created_at": r["created_at"]}
    if r["conversation_id"]:
        m["conversation_id"] = r["conversation_id"]
    if r["recipe_id"] is not None:
        m["recipe_id"] = r["recipe_id"]
    if r["sources_json"] is not None:
        m["sources"] = json.loads(r["sources_json"])
    return m


@router.get("/chats/{chat_id}")
def get_chat(chat_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    chat = conn.execute("SELECT * FROM chats WHERE chat_id = ? AND user_id = ?", (chat_id, user.user_id)).fetchone()
    if not chat:
        raise not_found()
    sel = conn.execute("SELECT * FROM selections WHERE chat_id = ?", (chat_id,)).fetchone()
    messages = [_message(r) for r in conn.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY seq", (chat_id,))]
    selected, resume = None, "ready"
    if chat["active_conversation_id"]:
        conv = conn.execute("SELECT recipe_json FROM conversations WHERE conversation_id = ?",
                            (chat["active_conversation_id"],)).fetchone()
        if conv:
            selected = json.loads(conv["recipe_json"])
            if not selected.get("steps"):
                resume = "recipe_unavailable"
    selection = _selection_payload(sel)
    return ok(request, {
        "chat_id": chat["chat_id"], "title": chat["title"], "created_at": chat["created_at"],
        "updated_at": chat["updated_at"], "messages": messages, "selection_id": sel["selection_id"],
        "products_text": chat["products_text"], "filters": selection["filters"],
        "selected_recipe": selected, "conversation_id": chat["active_conversation_id"] if selected else None,
        "resume_status": resume, "selection": selection})


@router.delete("/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    trace = Trace(rid(request))
    with Tx(conn):
        cur = conn.execute("DELETE FROM chats WHERE chat_id = ? AND user_id = ?", (chat_id, user.user_id))
        if cur.rowcount == 0:
            raise not_found()
    trace.skip("LLM")
    request.app.state.activity.record(conn, trace, "delete_chat", user.user_id)
    return Response(status_code=204)
