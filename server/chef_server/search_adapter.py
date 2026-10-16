"""Адаптер поиска: загрузка модуля search/rag (собственный BM25 Александры) и каталога рецептов.

Модуль поиска не изменяется. Сервис:
- загружает RecipeSearcher один раз (индекс строится/читается модулем поиска);
- поднимает RecipeCatalog: применяет к индексу изменения администратора из БД;
- отдаёт подбор, фильтры, полный рецепт и данные для /admin/rag через каталог.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path

from .db import init_db
from .errors import ApiError, search_unavailable, validation

log = logging.getLogger("chef.search")


class SearchService:
    def __init__(self, search_dir: Path, corpus_path: Path | None, mode: str, db_path: Path | None = None):
        self.search_dir = Path(search_dir)
        self.requested_corpus = corpus_path
        self.requested_mode = mode
        self.db_path = db_path
        self._searcher = None
        self.catalog = None
        self._error: str | None = None
        self._lock = threading.Lock()
        self.corpus_path: Path | None = None

    # ---------------------------------------------------------------- загрузка
    def _import_path(self) -> None:
        if str(self.search_dir) not in sys.path:
            sys.path.insert(0, str(self.search_dir))

    def _pick_corpus(self) -> Path:
        if self.requested_corpus:
            return Path(self.requested_corpus)
        full = self.search_dir / "data" / "corpus.jsonl"
        if full.exists():
            return full
        sample = self.search_dir / "data" / "sample_corpus.jsonl"
        log.warning("Полный корпус %s не найден, используется выборка %s (без шагов рецептов)", full, sample)
        return sample

    def use_searcher(self, searcher, corpus_name: str = "test_corpus", steps_store=None) -> None:
        """Подключить уже созданный RecipeSearcher (тесты)."""
        self._import_path()
        from .catalog import RecipeCatalog
        init_db(self.db_path)
        with self._lock:
            self._searcher = searcher
            self.corpus_path = Path(corpus_name + ".jsonl")
            self.catalog = RecipeCatalog(searcher, self.db_path, corpus_name, steps_store)
            self.catalog._key_index()

    def load(self) -> None:
        with self._lock:
            if self.catalog is not None:
                return
            try:
                self._import_path()
                from rag.corpus import StepsStore
                from rag.search import RecipeSearcher  # модуль Александры

                from .catalog import RecipeCatalog
                self.corpus_path = self._pick_corpus()
                t = time.perf_counter()
                searcher = RecipeSearcher.load(self.requested_mode, self.corpus_path)
                init_db(self.db_path)
                catalog = RecipeCatalog(searcher, self.db_path, self.corpus_path.stem, StepsStore())
                catalog._key_index()  # ключи дубликатов заранее, чтобы первая операция админа была быстрой
                self._searcher, self.catalog, self._error = searcher, catalog, None
                log.info("Поиск готов: корпус %s, режим %s, %d рецептов, ревизия каталога %d, %.1f с",
                         self.corpus_path.name, searcher.mode, catalog.live_count, catalog.revision,
                         time.perf_counter() - t)
            except Exception as exc:  # индекс/корпус недоступен — это ошибка поиска, не 500
                self._error = type(exc).__name__
                log.exception("Не удалось загрузить поиск")

    @property
    def ready(self) -> bool:
        return self.catalog is not None

    @property
    def cat(self):
        if self.catalog is None:
            self.load()
        if self.catalog is None:
            raise search_unavailable()
        return self.catalog

    # ---------------------------------------------------------------- версии для диагностики
    @property
    def corpus_version(self) -> str | None:
        return self.catalog.version if self.catalog else self._meta_version()

    def _meta_version(self) -> str | None:
        try:
            return json.loads((self.search_dir / "data" / "corpus_meta.json").read_text("utf-8"))["corpus_version"]
        except (OSError, ValueError, KeyError):
            return None

    @property
    def mode(self) -> str | None:
        return self._searcher.mode if self._searcher else None

    @property
    def index_version(self) -> str | None:
        return self.catalog.index_version if self.catalog else None

    @property
    def status(self) -> dict:
        c = self.catalog
        return {"ready": self.ready, "error": self._error, "corpus_version": self.corpus_version,
                "base_corpus_version": c.base_version if c else None,
                "corpus_file": self.corpus_path.name if self.corpus_path else None,
                "mode": self.mode, "index_version": self.index_version,
                "catalog": {"records": c.live_count, "revision": c.revision,
                            "stale_admin_changes": c.stale_rows} if c else None}

    # ---------------------------------------------------------------- операции подбора
    def query_terms(self, text: str) -> list[str]:
        self.cat
        return self._searcher.normalizer.tokens(text)

    def candidates(self, text: str) -> tuple[list[int], int, list[str]]:
        try:
            return self.cat.search_ids(text)
        except ApiError:
            raise
        except Exception:
            log.exception("Сбой поиска")
            raise search_unavailable()

    def page(self, ids: list[int], revision: int, tokens: list[str], filters: dict) -> tuple[list[dict], int]:
        try:
            return self.cat.page(ids, revision, tokens, filters)
        except ValueError as exc:
            raise validation(str(exc))
        except ApiError:
            raise
        except Exception:
            log.exception("Сбой фильтрации")
            raise search_unavailable()

    def full_recipe(self, recipe_id: int, revision: int) -> dict | None:
        try:
            return self.cat.full(recipe_id, revision)
        except ApiError:
            raise
        except Exception:
            log.exception("Сбой чтения рецепта")
            raise search_unavailable()
