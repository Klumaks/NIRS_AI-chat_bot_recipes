"""Каталог рецептов сервера: базовый корпус Александры + изменения администратора (ADM-04, SC-13).

Действующий каталог = записи корпуса search/data (файлы не меняются) + журнал изменений
администратора в SQLite (rag_changes). Каждая успешная операция создаёт новую ревизию R;
версия каталога — «<версия корпуса>+admin.R» (без изменений — просто версия корпуса).

Связь с поиском — только через публичный интерфейс модуля Александры: после изменения сервер
собирает новый индекс функцией RecipeSearcher.build по действующему каталогу и подменяет его
атомарно. Внутренности BM25 сервер не трогает. Пока идёт сборка, поиск работает по прежнему
индексу; запись в БД и подмена происходят только после успешной сборки.

Подбор хранит снимок ранжированных ID кандидатов и ревизию каталога. Фильтры, открытие
рецепта и вопросы старых чатов работают по версии записей на момент подбора, даже если
запись позже изменили или удалили (история версий хранится в rag_changes).
"""
from __future__ import annotations

import bisect
import json
import logging
import sqlite3
import threading
import zlib
from array import array
from contextlib import contextmanager
from dataclasses import dataclass

from .db import Tx, connect, dumps, now
from .errors import ApiError
from .rag_input import recipe_key

log = logging.getLogger("chef.catalog")

NUTRITION_KEYS = ("kcal", "protein_g", "fat_g", "carbs_g")


class RWLock:
    """Много читателей (поиск, фильтры) или один писатель (применение изменения индекса)."""

    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False

    @contextmanager
    def read(self):
        with self._cond:
            while self._writer:
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if not self._readers:
                    self._cond.notify_all()

    @contextmanager
    def write(self):
        with self._cond:
            while self._writer or self._readers:
                self._cond.wait()
            self._writer = True
        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()


@dataclass
class Change:
    """Одна операция каталога: recipe_id и новая запись (None — удаление)."""
    recipe_id: int
    record: dict | None


def pack_ids(ids: list[int]) -> bytes:
    return zlib.compress(array("q", ids).tobytes(), 6)


def unpack_ids(blob: bytes | None) -> list[int]:
    if not blob:
        return []
    a = array("q")
    a.frombytes(zlib.decompress(blob))
    return a.tolist()


class RecipeCatalog:
    def __init__(self, searcher, db_path, corpus_name: str, steps_store=None):
        from rag.search import RecipeSearcher, matches_filters  # модуль поиска Александры

        self._Searcher = RecipeSearcher
        self._matches = matches_filters
        self.base = searcher            # индекс чистого корпуса, как его загрузил модуль поиска
        self.s = searcher               # действующий индекс (после изменений администратора)
        self.norm = searcher.normalizer
        self.db_path = db_path
        self.steps_store = steps_store
        self.base_version: str = (searcher.meta or {}).get("corpus_version") or "unknown-corpus"
        self.built_at: str = (searcher.meta or {}).get("built_at") or ""
        # Ключ базы: версия корпуса + файл + число записей. Выборка и полный корпус с одной версией
        # различаются, поэтому изменения администратора к ним не смешиваются.
        self.base_key = f"{self.base_version}|{corpus_name}|{len(searcher.corpus)}"
        self.base_by_id: dict[int, dict] = {r["id"]: r for r in searcher.corpus}
        self.base_order = [r["id"] for r in searcher.corpus]
        self.revision = 0
        self.next_id = (max(self.base_by_id) + 1) if self.base_by_id else 1
        self.history: dict[int, list[tuple[int, str, dict | None, str]]] = {}  # id -> [(rev, op, record, at)]
        self.stale_rows = 0
        self.rw = RWLock()
        self.writer = threading.Lock()
        self._keys: dict[str, set[int]] | None = None
        self._live_ids: list[int] = list(self.base_order)
        self._replay()

    # ------------------------------------------------------------------ версии
    def version_of(self, revision: int) -> str:
        return self.base_version if revision == 0 else f"{self.base_version}+admin.{revision}"

    @property
    def version(self) -> str:
        return self.version_of(self.revision)

    @property
    def index(self):
        return self.s.index

    @property
    def live_count(self) -> int:
        return len(self._live_ids)

    @property
    def index_version(self) -> str:
        i = self.s.index
        return f"bm25:{self.base_key.split('|')[1]}:{self.s.mode}:N={i.N}:k1={i.k1}:b={i.b}:rev={self.revision}"

    def record_version(self, recipe_id: int) -> str | None:
        """Версия текущей записи (expected_version в PUT/DELETE)."""
        h = self.history.get(recipe_id)
        if h:
            rev, op, _rec, _at = h[-1]
            return None if op == "delete" else self.version_of(rev)
        return self.base_version if recipe_id in self.base_by_id else None

    # ------------------------------------------------------------------ загрузка изменений
    def _replay(self) -> None:
        conn = connect(self.db_path)
        try:
            state = conn.execute("SELECT revision, next_id FROM rag_state WHERE base_key = ?", (self.base_key,)).fetchone()
            rows = conn.execute("SELECT revision, recipe_id, op, record_json, created_at FROM rag_changes "
                                "WHERE base_key = ? ORDER BY revision, recipe_id", (self.base_key,)).fetchall()
            self.stale_rows = conn.execute("SELECT COUNT(*) FROM rag_changes WHERE base_key <> ?",
                                           (self.base_key,)).fetchone()[0]
        finally:
            conn.close()
        for r in rows:
            rec = json.loads(r["record_json"]) if r["record_json"] else None
            self.history.setdefault(r["recipe_id"], []).append((r["revision"], r["op"], rec, r["created_at"]))
        if state:
            self.revision = state["revision"]
            self.next_id = max(self.next_id, state["next_id"])
        if self.history:
            self.s = self._build(self.history)
        self._live_ids = self._live_order(self.history)
        if self.stale_rows:
            log.warning("В БД %d изменений каталога для другой версии корпуса: изменения не применены, "
                        "запись в каталог заблокирована (см. server/README.md, rag-export)", self.stale_rows)

    # ------------------------------------------------------------------ индекс
    @staticmethod
    def _latest(history: dict, recipe_id: int):
        h = history.get(recipe_id)
        return h[-1] if h else None

    def _live_order(self, history: dict) -> list[int]:
        """Порядок каталога как в моках: записи корпуса в исходном порядке (правка остаётся на месте),
        затем добавленные администратором по возрастанию ID; удалённые исключены."""
        out = []
        for rid in self.base_order:
            last = self._latest(history, rid)
            if last is None or last[1] == "upsert":
                out.append(rid)
        out += sorted(rid for rid, h in history.items() if rid not in self.base_by_id and h[-1][1] == "upsert")
        return out

    def _build(self, history: dict):
        """Новый индекс по действующему каталогу публичной функцией модуля поиска."""
        corpus = []
        for rid in self._live_order(history):
            last = self._latest(history, rid)
            corpus.append(self.base_by_id[rid] if last is None else dict(last[2], id=rid))
        idx = self.base.index
        searcher = self._Searcher.build(corpus, self.base.mode, idx.k1, idx.b)
        searcher.meta = self.base.meta
        return searcher

    # ------------------------------------------------------------------ чтение
    def resolve(self, recipe_id: int, revision: int) -> tuple[dict | None, str | None, dict | None]:
        """Запись в состоянии на ревизию: (record, версия записи, метаданные изменения)."""
        h = self.history.get(recipe_id)
        if h:
            i = bisect.bisect_right([e[0] for e in h], revision) - 1
            if i >= 0:
                rev, op, rec, at = h[i]
                return (None, None, None) if op == "delete" else (rec, self.version_of(rev), {"at": at})
        rec = self.base_by_id.get(recipe_id)
        return (rec, self.base_version, None) if rec is not None else (None, None, None)

    def search_ids(self, text: str) -> tuple[list[int], int, list[str]]:
        """Все кандидаты BM25 в порядке ранжирования модуля поиска (покрытие запроса, затем BM25)."""
        tokens = self.norm.tokens(text)
        with self.rw.read():
            ranked = self.s.index.search(tokens, None, False, coverage_first=True) if tokens else []
            return [self.s.corpus[d]["id"] for d, _ in ranked], self.revision, tokens

    def page(self, ids: list[int], revision: int, tokens: list[str], filters: dict, k: int = 5):
        """Фильтры по всему снимку подбора до отбора первых k; total — после фильтров."""
        q_set = set(tokens)
        active = any(filters.values()) if filters else False
        items, total = [], 0
        with self.rw.read():
            for rid in ids:
                rec, _ver, meta = self.resolve(rid, revision)
                if rec is None or (active and not self._matches(rec, filters)):
                    continue
                total += 1
                if len(items) < k:
                    items.append(self.card(rid, rec, meta, self.s.missing(rec, q_set)["missing_ingredients"]))
        return items, total

    def steps_of(self, recipe_id: int, record: dict) -> list[str]:
        if "steps" in record:
            raw = record["steps"] or []
        elif self.steps_store is not None:
            raw = self.steps_store.get(recipe_id)
        else:
            raw = []
        return [s for s in raw if isinstance(s, str) and s.strip()]

    def full(self, recipe_id: int, revision: int) -> dict | None:
        rec, ver, meta = self.resolve(recipe_id, revision)
        if rec is None:
            return None
        card = self.card(recipe_id, rec, meta, [])
        card["steps"] = self.steps_of(recipe_id, rec)
        card["corpus_version"] = ver
        card["verified_version"] = (f"{ver} · ввод администратора без внешней проверки" if meta else
                                    f"{ver} · данные источника без ручной проверки")
        if card["steps"]:
            card["provenance"]["steps"] = self._prov(rec, meta, "source")
        return card

    # ------------------------------------------------------------------ админ-список
    def list_page(self, offset: int, limit: int) -> tuple[list[dict], int]:
        with self.rw.read():
            ids = self._live_ids[offset: offset + limit]
            return [self.full(rid, self.revision) for rid in ids], len(self._live_ids)

    # ------------------------------------------------------------------ дубликаты
    def _key_index(self) -> dict[str, set[int]]:
        if self._keys is None:
            keys: dict[str, set[int]] = {}
            for rid in self._live_ids:
                rec, _v, _m = self.resolve(rid, self.revision)
                if rec is not None and rec.get("ingredients"):
                    keys.setdefault(recipe_key(rec), set()).add(rid)
            self._keys = keys
        return self._keys

    def duplicate_of(self, record: dict, exclude: int | None = None) -> int | None:
        ids = self._key_index().get(recipe_key(record), set()) - ({exclude} if exclude is not None else set())
        return min(ids) if ids else None

    # ------------------------------------------------------------------ запись
    def commit(self, conn: sqlite3.Connection, changes: list[Change], user_id: str, expected: dict[int, str],
               on_commit, trace=None) -> dict:
        """Атомарная операция каталога: проверка → сборка нового индекса → запись в БД → подмена.

        expected: recipe_id -> ожидаемая версия (PUT/DELETE). on_commit(conn, version, ids) пишет
        событие журнала в той же транзакции. Новым записям (recipe_id < 0) назначаются постоянные ID.
        Если сборка или запись не удались, ни БД, ни действующий индекс не меняются."""
        stage = trace.stage if trace else (lambda _n: _null())
        with self.writer:
            if self.stale_rows:
                raise ApiError(409, "CATALOG_STALE", "Корпус пересобран: изменения администратора для прежней "
                               "версии не применены. Выполните перенос (server/README.md) и повторите.")
            with stage("Проверка версии и дубликатов"):
                for rid, exp in expected.items():
                    cur = self.record_version(rid)
                    if cur is None:
                        raise ApiError(404, "NOT_FOUND", "Рецепт удалён или не найден. Обновите список.")
                    if cur != exp:
                        raise ApiError(409, "VERSION_CONFLICT",
                                       "Запись уже изменена. Обновите список и откройте актуальную запись.")
                next_id = self.next_id
                prepared: list[Change] = []
                for ch in changes:
                    rid = ch.recipe_id
                    if rid < 0:
                        rid, next_id = next_id, next_id + 1
                    if ch.record is not None:
                        dup = self.duplicate_of(ch.record, exclude=rid)
                        if dup is not None:
                            raise ApiError(409, "DUPLICATE_RECIPE", f"Такой рецепт уже существует (ID {dup}).")
                    prepared.append(Change(rid, ch.record))
            revision = self.revision + 1
            at = now()
            history = {rid: list(h) for rid, h in self.history.items()}
            for ch in prepared:
                history.setdefault(ch.recipe_id, []).append(
                    (revision, "delete" if ch.record is None else "upsert", ch.record, at))
            try:
                with stage("Сборка индекса BM25 модулем поиска"):
                    searcher = self._build(history)
            except Exception:
                log.exception("Не удалось собрать индекс после изменения каталога")
                raise ApiError(503, "SEARCH_UNAVAILABLE", "Не удалось обновить поисковый индекс. "
                               "Изменение не сохранено, повторите позже.")
            version = self.version_of(revision)
            with stage("Сохранение изменений в БД"):
                with Tx(conn):
                    for ch in prepared:
                        conn.execute("INSERT INTO rag_changes(base_key, revision, recipe_id, op, record_json, user_id,"
                                     " created_at) VALUES (?,?,?,?,?,?,?)",
                                     (self.base_key, revision, ch.recipe_id, "delete" if ch.record is None else "upsert",
                                      None if ch.record is None else dumps(ch.record), user_id, at))
                    conn.execute("INSERT INTO rag_state(base_key, revision, next_id) VALUES (?,?,?) "
                                 "ON CONFLICT(base_key) DO UPDATE SET revision = excluded.revision, "
                                 "next_id = excluded.next_id", (self.base_key, revision, next_id))
                    on_commit(conn, version, [c.recipe_id for c in prepared])
            with stage("Подмена индекса"):
                keys = self._key_index()
                with self.rw.write():
                    for ch in prepared:
                        old, _v, _m = self.resolve(ch.recipe_id, self.revision)
                        if old is not None and old.get("ingredients"):
                            keys.get(recipe_key(old), set()).discard(ch.recipe_id)
                        if ch.record is not None:
                            keys.setdefault(recipe_key(ch.record), set()).add(ch.recipe_id)
                    self.history = history
                    self.s = searcher
                    self._live_ids = self._live_order(history)
                    self.revision, self.next_id = revision, next_id
        return {"corpus_version": version, "ids": [c.recipe_id for c in prepared], "revision": revision}

    # ------------------------------------------------------------------ карточки
    def _prov(self, rec: dict, meta: dict | None, method: str) -> dict:
        if meta is not None:  # ввод администратора
            return {"source_ref": rec["url"], "method": "editorial",
                    "checked_by": "ввод администратора, внешней проверки нет", "checked_at": meta["at"]}
        ref = rec["url"] if method == "source" else (
            f"{rec['url']} · калькулятор povarenok.ru по составу; spec/tech/rag.md, corpus_meta.json "
            f"{self.base_version}")
        return {"source_ref": ref, "method": method,
                "checked_by": "не проверялось вручную (данные povarenok.ru)", "checked_at": self.built_at}

    def card(self, recipe_id: int, rec: dict, meta: dict | None, missing: list[str]) -> dict:
        n = rec.get("nutrition_per_100g") or {}
        nutrition = {k: n.get(k) for k in NUTRITION_KEYS}
        provenance = {}
        if rec.get("description"):
            provenance["description"] = self._prov(rec, meta, "source")
        if rec.get("total_time_minutes") is not None:
            provenance["total_time_minutes"] = self._prov(rec, meta, "source")
        for key in NUTRITION_KEYS:
            if nutrition[key] is not None:
                provenance[key] = self._prov(rec, meta, "calculation")
        return {
            "recipe_id": int(recipe_id), "title": rec["title"], "description": rec.get("description"),
            "ingredients": [{"name": i["name"], "amount": i.get("amount")} for i in rec["ingredients"]],
            "url": rec["url"], "nutrition_per_100g": nutrition,
            "total_time_minutes": rec.get("total_time_minutes"),
            "missing_ingredients": list(missing), "provenance": provenance,
            "data_mode": "verified",  # по контракту: ответ сервера; фактическая проверка — в provenance
        }


@contextmanager
def _null():
    yield None
