"""Журнал активности и диагностика этапов запроса (ADM-02, ADM-03, SC-09).

В журнал и диагностику НЕ попадают: пароли, токены, текст продуктов, вопросы и ответы,
промпты. Сохраняются время, пользователь, тип, статус, длительность, request_id, а для
диагностики — этапы, режим нормализации, версии, ID рецептов, модель и безопасный код ошибки.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import timedelta

from .db import dumps, now
from .security import iso, utcnow

EVENT_TYPES = {
    "register", "login", "logout", "create_user", "search", "filter",
    "select_recipe", "question", "delete_chat", "error",
    "rag_add", "rag_import", "rag_update", "rag_delete",
}
NOT_RUN = "not_run"


class Trace:
    """Этапы одного запроса с длительностями. Неиспользованные этапы явно отмечаются not_run."""

    def __init__(self, request_id: str):
        self.request_id = request_id
        self.started = time.perf_counter()
        self.stages: list[dict] = []
        self.info: dict = {
            "corpus_version": None, "index_version": None, "normalization_mode": None,
            "candidate_ids": [], "selected_recipe_id": None, "llm_called": False,
            "model": None, "error_code": None,
        }

    @contextmanager
    def stage(self, name: str):
        t = time.perf_counter()
        entry = {"name": name, "status": "ok", "duration_ms": None}
        self.stages.append(entry)
        try:
            yield entry
        except Exception:
            entry["status"] = "error"
            raise
        finally:
            entry["duration_ms"] = round((time.perf_counter() - t) * 1000)

    def skip(self, name: str) -> None:
        self.stages.append({"name": name, "status": NOT_RUN, "duration_ms": None})

    def elapsed_ms(self) -> int:
        return round((time.perf_counter() - self.started) * 1000)

    def diagnostic(self) -> dict:
        return {"request_id": self.request_id, **self.info, "stages": self.stages}


class ActivityLog:
    def __init__(self, retention_days: int):
        self.retention_days = retention_days
        self._last_purge = 0.0
        self._lock = threading.Lock()

    def record(self, conn: sqlite3.Connection, trace: Trace, event_type: str, user_id: str | None,
               status: str = "ok", target_user_id: str | None = None,
               assigned_role: str | None = None, recipe_id: int | None = None,
               count: int | None = None, corpus_version: str | None = None) -> None:
        assert event_type in EVENT_TYPES, event_type
        ts = now()
        conn.execute(
            "INSERT INTO events(occurred_at, user_id, event_type, status, duration_ms, request_id,"
            " target_user_id, assigned_role, recipe_id, count, corpus_version) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ts, user_id, event_type, status, trace.elapsed_ms(), trace.request_id,
             target_user_id, assigned_role, recipe_id, count, corpus_version))
        conn.execute("INSERT OR REPLACE INTO diagnostics(request_id, created_at, data_json) VALUES (?,?,?)",
                     (trace.request_id, ts, dumps(trace.diagnostic())))
        self.purge(conn)

    def purge(self, conn: sqlite3.Connection, force: bool = False) -> None:
        """Удаляет события и диагностику старше срока хранения (30 дней). Чаты не затрагиваются."""
        with self._lock:
            if not force and time.monotonic() - self._last_purge < 600:
                return
            self._last_purge = time.monotonic()
        border = iso(utcnow() - timedelta(days=self.retention_days))
        conn.execute("DELETE FROM events WHERE occurred_at < ?", (border,))
        conn.execute("DELETE FROM diagnostics WHERE created_at < ?", (border,))
