"""Управление данными RAG администратором (ADM-04, SC-13): список, добавление, импорт JSONL,
редактирование и удаление записей каталога с атомарным обновлением индекса BM25.

Права проверяются до разбора тела запроса: гость получает 401, пользователь — 403."""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request

from .activity import Trace
from .catalog import Change
from .db import dumps
from .deps import get_conn, ok, page_params, require_admin, rid
from .errors import ApiError, not_found, validation
from .rag_input import MAX_JSONL_BYTES, parse_jsonl, parse_recipe, recipe_key

router = APIRouter()
MAX_BODY = 4 * MAX_JSONL_BYTES  # JSON-строка с экранированием больше исходного файла


async def raw_body(request: Request) -> bytes:
    """Тело читается без разбора: сначала проверяются права, потом содержимое."""
    return await request.body()


def _json(raw: bytes) -> dict:
    if len(raw) > MAX_BODY:
        raise validation("Файл превышает 5 МиБ")
    try:
        value = json.loads(raw or b"null")
    except ValueError:
        raise validation("Некорректный JSON запроса.")
    if not isinstance(value, dict):
        raise validation("Передайте JSON-объект.")
    return value


def _recipe_or_400(request: Request, body: dict) -> dict:
    record, problems = parse_recipe(body)
    if problems:
        raise validation("; ".join(problems))
    return record


def _text(body: dict) -> str:
    if not isinstance(body.get("text"), str):
        raise validation("Передайте текст JSONL в поле text.")
    return body["text"]


def _recipe_id(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise not_found("Рецепт удалён или не найден. Обновите список.")


def _expected(body: dict) -> str:
    v = body.get("expected_version")
    if not isinstance(v, str) or not v.strip():
        raise validation("Передайте expected_version записи.")
    return v


def _write(request: Request, conn, admin, event_type: str, changes: list[Change], expected: dict[int, str],
           count: int, recipe_id: int | None = None) -> dict:
    st = request.app.state
    trace = Trace(rid(request))
    cat = st.search.cat

    def on_commit(c, version, ids):  # событие журнала — в той же транзакции, что и изменение
        trace.info.update(corpus_version=version, normalization_mode=st.search.mode,
                          candidate_ids=ids[:100], selected_recipe_id=recipe_id)
        st.activity.record(c, trace, event_type, admin.user_id, recipe_id=recipe_id if recipe_id is not None
                           else (ids[0] if len(ids) == 1 else None), count=count, corpus_version=version)

    try:
        result = cat.commit(conn, changes, admin.user_id, expected, on_commit, trace)
    except ApiError as exc:
        trace.info.update(error_code=exc.code, corpus_version=cat.version, selected_recipe_id=recipe_id)
        trace.skip("LLM")
        st.activity.record(conn, trace, event_type, admin.user_id, status="error", recipe_id=recipe_id)
        raise
    # Полная диагностика с этапом применения к индексу и новой версией индекса
    trace.info["index_version"] = cat.index_version
    trace.skip("LLM")
    conn.execute("UPDATE diagnostics SET data_json = ? WHERE request_id = ?",
                 (dumps(trace.diagnostic()), rid(request)))
    return result


@router.get("/admin/rag")
def list_rag(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    require_admin(request, conn)
    limit, offset = page_params(request)
    cat = request.app.state.search.cat
    items, total = cat.list_page(offset, limit)
    return ok(request, {"items": items, "total": total, "corpus_version": cat.version})


@router.post("/admin/rag/recipes", status_code=201)
def add_recipe(request: Request, raw: bytes = Depends(raw_body), conn: sqlite3.Connection = Depends(get_conn)):
    admin = require_admin(request, conn)
    record = _recipe_or_400(request, _json(raw))
    result = _write(request, conn, admin, "rag_add", [Change(-1, record)], {}, 1)
    return ok(request, {"recipe_id": result["ids"][0], "corpus_version": result["corpus_version"]})


@router.put("/admin/rag/recipes/{recipe_id}")
def update_recipe(recipe_id: str, request: Request, raw: bytes = Depends(raw_body),
                  conn: sqlite3.Connection = Depends(get_conn)):
    admin = require_admin(request, conn)
    rid_ = _recipe_id(recipe_id)
    body = _json(raw)
    expected = _expected(body)
    cat = request.app.state.search.cat
    if cat.record_version(rid_) is None:
        raise not_found("Рецепт удалён или не найден. Обновите список.")
    record = _recipe_or_400(request, body)
    result = _write(request, conn, admin, "rag_update", [Change(rid_, record)], {rid_: expected}, 1, rid_)
    return ok(request, {"recipe_id": rid_, "corpus_version": result["corpus_version"]})


@router.delete("/admin/rag/recipes/{recipe_id}")
def delete_recipe(recipe_id: str, request: Request, raw: bytes = Depends(raw_body),
                  conn: sqlite3.Connection = Depends(get_conn)):
    admin = require_admin(request, conn)
    rid_ = _recipe_id(recipe_id)
    expected = _expected(_json(raw))
    result = _write(request, conn, admin, "rag_delete", [Change(rid_, None)], {rid_: expected}, 1, rid_)
    return ok(request, {"recipe_id": rid_, "corpus_version": result["corpus_version"]})


def _report(request: Request, text: str) -> tuple[dict, list[dict]]:
    """Проверка файла без записи: ошибки строк, дубликаты внутри файла и с каталогом."""
    cat = request.app.state.search.cat
    records, errors, count = parse_jsonl(text)
    duplicates, seen = [], {}
    for line, record in records:
        key = recipe_key(record)
        if key in seen or cat.duplicate_of(record) is not None:
            duplicates.append({"line": line, "message": "Рецепт уже существует или повторён в файле"})
        seen.setdefault(key, line)
    report = {"count": count, "errors": errors, "duplicates": duplicates,
              "valid": not errors and not duplicates}
    return report, [r for _l, r in records]


@router.post("/admin/rag/import/validate")
def validate_import(request: Request, raw: bytes = Depends(raw_body), conn: sqlite3.Connection = Depends(get_conn)):
    require_admin(request, conn)
    report, _records = _report(request, _text(_json(raw)))
    return ok(request, report)


@router.post("/admin/rag/import", status_code=201)
def import_recipes(request: Request, raw: bytes = Depends(raw_body), conn: sqlite3.Connection = Depends(get_conn)):
    admin = require_admin(request, conn)
    report, records = _report(request, _text(_json(raw)))  # повторная проверка перед записью
    if report["errors"]:
        raise validation("; ".join(f"Строка {e['line']}: {e['message']}" for e in report["errors"]))
    if report["duplicates"]:
        raise ApiError(409, "DUPLICATE_RECIPE",
                       "; ".join(f"Строка {e['line']}: {e['message']}" for e in report["duplicates"]))
    result = _write(request, conn, admin, "rag_import", [Change(-1 - i, r) for i, r in enumerate(records)], {},
                    len(records))
    return ok(request, {"added": len(result["ids"]), "corpus_version": result["corpus_version"]})
