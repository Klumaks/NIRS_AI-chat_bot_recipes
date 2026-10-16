"""Сервер с настоящим модулем поиска (собственный BM25) на выборке из Git, раздача фронтенда."""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ORIGIN
from fastapi.testclient import TestClient

from chef_server.app import create_app
from chef_server.search_adapter import SearchService

SEARCH = Path(__file__).resolve().parents[2] / "search"
SAMPLE = SEARCH / "data" / "sample_corpus.jsonl"


@pytest.fixture(scope="module")
def real_search(tmp_path_factory):
    if not SAMPLE.exists():
        pytest.skip("нет search/data/sample_corpus.jsonl")
    svc = SearchService(SEARCH, SAMPLE, "lemma", tmp_path_factory.mktemp("rs") / "real.sqlite3")
    svc.load()
    assert svc.ready, svc.status
    return svc


def test_real_bm25_selection_filters_and_incomplete(settings, real_search):
    settings.db_path = real_search.db_path
    with TestClient(create_app(settings, search=real_search), base_url="http://localhost:8000") as c:
        c.post("/api/v1/auth/register", json={"email": "r@test.ru", "password": "Password123"}, headers=ORIGIN)
        c.post("/api/v1/auth/login", json={"email": "r@test.ru", "password": "Password123"}, headers=ORIGIN)
        r = c.post("/api/v1/selections", json={"products_text": "Есть курица, рис и лук"}, headers=ORIGIN)
        assert r.status_code == 201
        sel = r.json()
        assert sel["total"] > 5 and len(sel["items"]) == 5
        assert sel["corpus_version"] == real_search.corpus_version
        assert all("difficulty" not in card for card in sel["items"])
        for card in sel["items"]:
            assert card["url"].startswith("https://www.povarenok.ru/")
            assert "Соль" not in card["missing_ingredients"]  # базовые продукты не выводятся
        f = {"kcal": {"min": 0, "max": 150}, "max_total_time_minutes": 60}
        r = c.post(f"/api/v1/selections/{sel['selection_id']}/filter", json={"filters": f}, headers=ORIGIN)
        out = r.json()
        assert r.status_code == 200 and out["total"] < sel["total"]
        for card in out["items"]:
            assert card["nutrition_per_100g"]["kcal"] <= 150 and card["total_time_minutes"] <= 60
        # в выборке из Git нет файла шагов: выбор рецепта честно сообщает о неполноте
        if not (SEARCH / "data" / "steps.jsonl").exists():
            rid = out["items"][0]["recipe_id"]
            r = c.post(f"/api/v1/selections/{sel['selection_id']}/recipe", json={"recipe_id": rid}, headers=ORIGIN)
            assert r.status_code == 409 and r.json()["error"]["code"] == "RECIPE_INCOMPLETE"
            assert r.json()["error"]["source_url"].startswith("https://www.povarenok.ru/")
        health = c.get("/api/v1/health").json()
        assert health["search"]["ready"] and health["search"]["mode"] in {"lemma", "stem"}


def test_spa_fallback_and_api_not_swallowed(settings, tmp_path, real_search):
    settings.db_path = real_search.db_path
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>chef</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    settings.serve_frontend, settings.frontend_dist = True, dist
    with TestClient(create_app(settings, search=real_search)) as c:
        assert c.get("/chat/abc/recipe/1").text == "<html>chef</html>"
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/../../etc/passwd").text == "<html>chef</html>"
        r = c.get("/api/v1/unknown")
        assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_admin_recipe_on_real_bm25(settings, real_search):
    """Админ добавляет рецепт в каталог с настоящим BM25 по выборке: он сразу находится и открывается."""
    import time
    from conftest import Api
    settings.db_path = real_search.db_path
    from chef_server.db import connect
    from chef_server.routes_auth import create_account
    conn = connect(settings.db_path)
    create_account(conn, "real-admin@test.ru", "Password123", "admin")
    conn.close()
    api = Api(create_app(settings, search=real_search))
    api.post("/auth/login", {"email": "real-admin@test.ru", "password": "Password123"})
    recipe = {"title": "Кумкват в карамели", "url": "https://example.org/kumquat",
              "ingredients": [{"name": "Кумкват", "amount": "300 г"}, {"name": "Сахар"}],
              "steps": ["Нарезать.", "Карамелизовать 10 минут."], "nutrition_per_100g": {"kcal": 120}}
    t = time.perf_counter()
    r = api.post("/admin/rag/recipes", recipe)
    took = time.perf_counter() - t
    assert r.status_code == 201, r.text
    new_id = r.json()["recipe_id"]
    assert new_id > max(real_search.catalog.base_by_id) and took < 2
    sel = api.post("/selections", {"products_text": "кумкват"}).json()
    assert [i["recipe_id"] for i in sel["items"]] == [new_id]
    rec = api.post(f"/selections/{sel['selection_id']}/recipe", {"recipe_id": new_id}).json()
    assert rec["steps"] == recipe["steps"]
    base = api.get("/admin/rag?offset=1&limit=1").json()["items"][0]
    assert base["url"].startswith("https://www.povarenok.ru/")
    r = api.c.request("DELETE", f"/api/v1/admin/rag/recipes/{base['recipe_id']}",
                      json={"expected_version": base["corpus_version"]}, headers=ORIGIN)
    assert r.status_code == 200
    assert api.get("/admin/rag").json()["total"] == 2000  # 2000 + 1 − 1
    api.close()
