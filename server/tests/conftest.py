"""Фикстуры интеграционных тестов сервера.

Поиск — настоящий RecipeSearcher модуля search/ (собственный BM25, лемматизация pymorphy3),
собранный на 8 тестовых рецептах с шагами: так проверяется путь «подбор → рецепт → вопрос»
без полного корпуса. Выборка из Git проверяется отдельно в test_real_search.py.
LLM подменяется на уровне HTTP (httpx.MockTransport): работает настоящий адаптер.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chef_server.app import create_app  # noqa: E402
from chef_server.config import Settings  # noqa: E402
from chef_server.db import connect  # noqa: E402
from chef_server.llm import LLMClient  # noqa: E402
from chef_server.search_adapter import SearchService  # noqa: E402

ORIGIN = {"Origin": "http://localhost:5173"}
VERSION = "test-corpus-v1"


def _r(i, title, ings, kcal=None, time=None, steps=None, url=None):
    return {"id": i, "title": title, "description": f"Описание {title}",
            "ingredients": [{"name": n, "amount": a} for n, a in ings],
            "url": url or f"https://example.test/r/{i}", "categories": [],
            "total_time_minutes": time, "portions": 2,
            "nutrition_per_100g": {"kcal": kcal, "protein_g": None if kcal is None else 10.0,
                                   "fat_g": None if kcal is None else 5.0,
                                   "carbs_g": None if kcal is None else 20.0},
            "has_steps": bool(steps), "steps": steps or []}


RECIPES = [
    _r(1, "Рис с курицей", [("Курица", "300 г"), ("Рис", "1 стак."), ("Лук", "1 шт"), ("Вода", "300 мл")],
       kcal=150, time=30, steps=["Нарезать курицу и лук.", "Обжарить 10 минут.", "Добавить рис и воду, тушить 20 минут."]),
    _r(2, "Курица с луком", [("Курица", "500 г"), ("Лук", None)], kcal=180, time=31,
       steps=["Нарезать.", "Запечь."]),
    _r(3, "Плов", [("Рис", "2 стак."), ("Морковь", "2 шт"), ("Баранина", "500 г")], kcal=None, time=None,
       steps=["Обжарить мясо.", "Добавить рис."]),
    _r(4, "Рисовая каша", [("Рис", "1 стак."), ("Молоко", "1 л")], kcal=100, time=25, steps=None),
    _r(5, "Куриный суп", [("Курица", "300 г"), ("Картофель", "3 шт")], kcal=40, time=60, steps=["Варить."]),
    _r(6, "Курица в сливках", [("Курица", "400 г"), ("Сливки", "200 мл")], kcal=200, time=40, steps=["Тушить."]),
    _r(7, "Курица гриль", [("Курица", "1 шт")], kcal=210, time=90, steps=["Запечь."]),
    _r(8, "Курица терияки", [("Курица", "400 г"), ("Соус", "50 мл")], kcal=160, time=20, steps=["Обжарить."]),
]
SEARCH_DIR = Path(__file__).resolve().parents[2] / "search"
sys.path.insert(0, str(SEARCH_DIR))


def build_searcher(recipes=None, version=VERSION):
    """Настоящий RecipeSearcher модуля поиска (BM25, лемматизация) на тестовых рецептах.
    Шаги лежат прямо в записях (поле steps) — сервер берёт их оттуда вместо steps.jsonl."""
    from rag.search import RecipeSearcher
    searcher = RecipeSearcher.build([dict(r) for r in (recipes or RECIPES)], "lemma")
    searcher.meta = {"corpus_version": version, "built_at": "2026-10-15T00:00:00Z"}
    return searcher


class FakeLLM:
    """OpenAI-совместимый сервер в памяти; записывает запросы для проверки промпта."""

    def __init__(self):
        self.requests: list[dict] = []
        self.reply = {"status": "answered", "answer": "На втором шаге обжарьте 10 минут.", "step_numbers": [2, 99]}
        self.status_code = 200
        self.raise_exc: Exception | None = None
        self.on_call = None
        self.reject_json_mode = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append({"body": body, "headers": dict(request.headers)})
        if self.on_call:
            self.on_call()
        if self.raise_exc:
            raise self.raise_exc
        if self.reject_json_mode and "response_format" in body:
            return httpx.Response(400, json={"error": "response_format unsupported"})
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"error": "fail"})
        content = self.reply if isinstance(self.reply, str) else json.dumps(self.reply, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def searcher():
    return build_searcher()


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.db_path = tmp_path / "test.sqlite3"
    s.search_preload = False
    s.serve_frontend = False
    s.frontend_dist = tmp_path / "no-dist"
    return s


def make_service(searcher, db_path, corpus_name="test_corpus"):
    svc = SearchService(SEARCH_DIR, None, "lemma", db_path)
    svc.use_searcher(searcher, corpus_name)
    return svc


@pytest.fixture
def app(settings, searcher, fake_llm):
    llm = LLMClient("openai_compatible", "http://llm.test/v1", "secret-key", "test-model", 5, 0.2, True,
                    12000, 10, transport=httpx.MockTransport(fake_llm.handler))
    return create_app(settings, search=make_service(searcher, settings.db_path), llm=llm)


class Api:
    """Клиент одного браузера: свои cookie, Origin фронтенда."""

    def __init__(self, app):
        self.c = TestClient(app, base_url="http://localhost:8000")
        self.c.__enter__()

    def get(self, path, **kw):
        return self.c.get("/api/v1" + path, headers=ORIGIN, **kw)

    def post(self, path, body=None, **kw):
        return self.c.post("/api/v1" + path, json={} if body is None else body, headers=ORIGIN, **kw)

    def delete(self, path):
        return self.c.delete("/api/v1" + path, headers=ORIGIN)

    def register_login(self, email, password="Password123"):
        assert self.post("/auth/register", {"email": email, "password": password}).status_code == 201
        r = self.post("/auth/login", {"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()

    def close(self):
        self.c.__exit__(None, None, None)


@pytest.fixture
def client_factory(app):
    made = []

    def make():
        api = Api(app)
        made.append(api)
        return api
    yield make
    for api in made:
        api.close()


@pytest.fixture
def make_admin(settings):
    def make(email="root@ai-chef.test", password="RootPass123"):
        from chef_server.db import init_db
        from chef_server.routes_auth import create_account
        init_db(settings.db_path)
        conn = connect(settings.db_path)
        try:
            create_account(conn, email, password, "admin")
        finally:
            conn.close()
        return email, password
    return make


def db_dump(settings) -> str:
    """Всё содержимое журнала и диагностики одной строкой — для поиска утечек текста."""
    conn = connect(settings.db_path)
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM events")]
        rows += [dict(r) for r in conn.execute("SELECT * FROM diagnostics")]
    finally:
        conn.close()
    return json.dumps(rows, ensure_ascii=False)
