"""Управление данными RAG на сервере (ADM-04, SC-13): права, проверка, импорт, версии,
атомарное обновление BM25, снимки старых чатов, перезапуск и соответствие полной пересборке."""
from __future__ import annotations

import json
import random
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from conftest import RECIPES, VERSION, build_searcher, db_dump, make_service

from chef_server.app import create_app

SERVER = Path(__file__).resolve().parents[1]

NEW = {"title": "Кумкват в карамели", "url": "https://example.org/kumquat",
       "ingredients": [{"name": "Кумкват", "amount": "300 г"}, {"name": "Сахар", "amount": "100 г"}],
       "description": "Десерт", "steps": ["Нарезать кумкват.", "Сварить с сахаром 15 минут."],
       "nutrition_per_100g": {"kcal": 210, "protein_g": 1, "fat_g": None, "carbs_g": 50},
       "total_time_minutes": 25}


def _admin(client_factory, make_admin):
    email, pw = make_admin()
    api = client_factory()
    assert api.post("/auth/login", {"email": email, "password": pw}).status_code == 200
    return api


def _put(api, rid, body):
    return api.c.put(f"/api/v1/admin/rag/recipes/{rid}", json=body, headers={"Origin": "http://localhost:5173"})


def _delete(api, rid, expected):
    return api.c.request("DELETE", f"/api/v1/admin/rag/recipes/{rid}", json={"expected_version": expected},
                         headers={"Origin": "http://localhost:5173"})


def _ids(api, text):
    r = api.post("/selections", {"products_text": text})
    assert r.status_code == 201, r.text
    return r.json(), [i["recipe_id"] for i in r.json()["items"]]


def test_roles_before_body(client_factory):
    guest = client_factory()
    user = client_factory()
    user.register_login("u@rag.test")
    calls = [("get", "/admin/rag", None), ("post", "/admin/rag/recipes", "{bad"),
             ("post", "/admin/rag/import/validate", "{bad"), ("post", "/admin/rag/import", "{bad"),
             ("put", "/admin/rag/recipes/1", "{bad"), ("delete", "/admin/rag/recipes/1", "{bad")]
    for api, status, code in ((guest, 401, "AUTH_REQUIRED"), (user, 403, "FORBIDDEN")):
        for method, path, body in calls:
            r = api.c.request(method.upper(), "/api/v1" + path, content=body,
                              headers={"Origin": "http://localhost:5173", "Content-Type": "application/json"})
            assert r.status_code == status and r.json()["error"]["code"] == code, (method, path, r.text)


def test_add_search_open_ask(client_factory, make_admin, fake_llm):
    admin = _admin(client_factory, make_admin)
    page = admin.get("/admin/rag").json()
    assert page["total"] == 8 and page["corpus_version"] == VERSION
    first = page["items"][0]
    assert first["recipe_id"] == 1 and first["corpus_version"] == VERSION and first["steps"]
    assert "difficulty" not in first and first["data_mode"] == "verified"
    r = admin.post("/admin/rag/recipes", NEW)
    assert r.status_code == 201, r.text
    assert r.json()["recipe_id"] == 9 and r.json()["corpus_version"] == VERSION + "+admin.1"
    page = admin.get("/admin/rag?offset=8&limit=3").json()
    assert page["total"] == 9 and page["items"][0]["recipe_id"] == 9  # порядок каталога, как в моках
    item = page["items"][0]
    assert item["data_mode"] == "verified" and item["provenance"]["kcal"]["method"] == "editorial"
    assert item["nutrition_per_100g"]["fat_g"] is None and item["corpus_version"] == VERSION + "+admin.1"
    assert [i["recipe_id"] for i in admin.get("/admin/rag?offset=7&limit=5").json()["items"]] == [8, 9]

    user = client_factory()
    user.register_login("eater@rag.test")
    sel, ids = _ids(user, "кумкват и сахар")
    assert ids == [9] and sel["corpus_version"] == VERSION + "+admin.1"
    rec = user.post(f"/selections/{sel['selection_id']}/recipe", {"recipe_id": 9}).json()
    assert rec["steps"] == NEW["steps"] and rec["corpus_version"] == VERSION + "+admin.1"
    r = user.post(f"/conversations/{rec['conversation_id']}/messages", {"message_id": "k1", "text": "Сколько варить?"})
    assert r.status_code == 200 and "Сварить с сахаром 15 минут." in fake_llm.requests[-1]["body"]["messages"][0]["content"]


def test_recipe_validation_and_duplicates(client_factory, make_admin):
    admin = _admin(client_factory, make_admin)
    bad = [
        {**NEW, "url": "ftp://example.org/x"}, {**NEW, "url": ""}, {**NEW, "title": "  "},
        {**NEW, "ingredients": [{"name": "Один"}]}, {**NEW, "ingredients": [{"name": "А"}, {"name": ""}]},
        {**NEW, "nutrition_per_100g": {"kcal": -1}}, {**NEW, "nutrition_per_100g": {"kcal": "100"}},
        {**NEW, "total_time_minutes": 0}, {**NEW, "total_time_minutes": 2.5}, {**NEW, "steps": ["ok", ""]},
        {**NEW, "description": ""}, {**NEW, "nutrition_per_100g": {"kcal": True}},
    ]
    for body in bad:
        r = admin.post("/admin/rag/recipes", body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR", body
    assert admin.get("/admin/rag").json()["corpus_version"] == VERSION  # ошибки не меняют версию
    minimal = {"title": "Гречка с грибами", "url": "https://example.org/g",
               "ingredients": [{"name": "Гречка"}, {"name": "Грибы", "amount": "200 г"}], "id": 777, "source": "x"}
    r = admin.post("/admin/rag/recipes", minimal)
    assert r.status_code == 201 and r.json()["recipe_id"] == 9  # исходный id не используется
    item = admin.get("/admin/rag?offset=8&limit=1").json()["items"][0]
    assert item["recipe_id"] == 9 and item["steps"] == [] and item["description"] is None and item["total_time_minutes"] is None
    assert item["nutrition_per_100g"] == {"kcal": None, "protein_g": None, "fat_g": None, "carbs_g": None}
    dup = {**minimal, "title": "ГРЕЧКА  с грибами", "ingredients": [{"name": "грибы"}, {"name": "Гречка"}]}
    r = admin.post("/admin/rag/recipes", dup)
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_RECIPE"
    base_dup = {"title": "рис с курицей", "url": "https://x.org",
                "ingredients": [{"name": n} for n in ("Курица", "Рис", "Лук", "Вода")]}
    assert admin.post("/admin/rag/recipes", base_dup).status_code == 409  # дубликат записи корпуса


def test_jsonl_validate_and_import(client_factory, make_admin, settings):
    admin = _admin(client_factory, make_admin)
    good = [{"title": f"Салат {i}", "url": f"https://example.org/{i}",
             "ingredients": [{"name": "Огурец"}, {"name": f"Специя{i}"}]} for i in range(3)]
    lines = [json.dumps(g, ensure_ascii=False) for g in good]
    text = "﻿" + lines[0] + "\n\n" + "\n".join(lines[1:]) + "\n"
    rep = admin.post("/admin/rag/import/validate", {"text": text}).json()
    assert rep["count"] == 3 and rep["valid"] and rep["errors"] == [] and rep["duplicates"] == []
    broken = lines[0] + "\n{не json\n" + json.dumps({"title": "X", "url": "https://a.b", "ingredients": [{"name": "A"}]}) \
        + "\n" + lines[0] + "\n" + json.dumps({"title": "рис с курицей", "url": "https://a.b",
                                                "ingredients": [{"name": n} for n in ("Курица", "Рис", "Лук", "Вода")]})
    rep = admin.post("/admin/rag/import/validate", {"text": broken}).json()
    assert not rep["valid"] and [e["line"] for e in rep["errors"]] == [2, 3]
    assert "ingredients" in rep["errors"][1]["message"]
    assert [d["line"] for d in rep["duplicates"]] == [4, 5]  # повтор в файле и дубликат корпуса
    for payload, code in ((broken, 400), (lines[0] + "\n" + lines[0], 409)):
        r = admin.post("/admin/rag/import", {"text": payload})
        assert r.status_code == code
    assert admin.get("/admin/rag").json()["total"] == 8  # атомарность: ни одной записи
    assert admin.post("/admin/rag/import/validate", {"text": "\n \n"}).json()["errors"][0]["message"] == "Файл не содержит записей"
    big = admin.post("/admin/rag/import/validate", {"text": "x" * (5 * 1024 * 1024 + 1)}).json()
    assert big["errors"] == [{"line": 1, "message": "Файл превышает 5 МиБ"}]
    many = "\n".join(json.dumps({**good[0], "title": f"Т{i}"}) for i in range(1001))
    rep = admin.post("/admin/rag/import/validate", {"text": many}).json()
    assert rep["errors"][-1] == {"line": 1001, "message": "Не более 1000 записей"}
    assert admin.post("/admin/rag/import/validate", {}).status_code == 400
    r = admin.post("/admin/rag/import", {"text": text})
    assert r.status_code == 201 and r.json() == {"added": 3, "corpus_version": VERSION + "+admin.1",
                                                  "request_id": r.json()["request_id"]}
    assert admin.get("/admin/rag").json()["total"] == 11
    ev = next(e for e in admin.get("/admin/activity").json()["items"] if e["event_type"] == "rag_import")
    assert ev["count"] == 3 and ev["corpus_version"] == VERSION + "+admin.1" and ev["status"] == "ok"
    assert "Салат" not in db_dump(settings) and "Огурец" not in db_dump(settings)  # без содержимого рецептов


def test_update_delete_versions_and_old_chats(client_factory, make_admin, fake_llm):
    admin = _admin(client_factory, make_admin)
    user = client_factory()
    user.register_login("old@rag.test")
    old_sel, old_ids = _ids(user, "Есть курица, рис и лук")
    old_filtered = user.post(f"/selections/{old_sel['selection_id']}/filter", {"filters": {"kcal": {"max": 200}}}).json()
    conv = user.post(f"/selections/{old_sel['selection_id']}/recipe", {"recipe_id": 1}).json()["conversation_id"]

    item = admin.get("/admin/rag").json()["items"][0]
    edited = {"title": "Рис с курицей по-новому", "url": item["url"], "steps": ["Новый шаг."],
              "ingredients": [{"name": "Курица"}, {"name": "Рис"}, {"name": "Шафран", "amount": "щепотка"}]}
    assert _put(admin, 1, edited).status_code == 400  # нет expected_version
    r = _put(admin, 1, {**edited, "expected_version": "stale"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "VERSION_CONFLICT"
    assert _put(admin, 999, {**edited, "expected_version": VERSION}).status_code == 404
    r = _put(admin, 1, {**edited, "expected_version": item["corpus_version"]})
    assert r.status_code == 200 and r.json()["recipe_id"] == 1 and r.json()["corpus_version"] == VERSION + "+admin.1"
    r = _put(admin, 1, {**edited, "expected_version": item["corpus_version"]})
    assert r.status_code == 409  # повтор со старой версией — конфликт
    dup = {"title": "Курица с луком", "url": "https://x.org", "ingredients": [{"name": "Курица"}, {"name": "Лук"}]}
    assert _put(admin, 1, {**dup, "expected_version": VERSION + "+admin.1"}).json()["error"]["code"] == "DUPLICATE_RECIPE"

    _sel, ids = _ids(user, "шафран")
    assert ids == [1]  # новый терм найден сразу после ответа
    sel_new, ids_new = _ids(user, "рис")
    rec_new = user.post(f"/selections/{sel_new['selection_id']}/recipe", {"recipe_id": 1}).json()
    assert rec_new["title"] == "Рис с курицей по-новому" and rec_new["steps"] == ["Новый шаг."]

    # старый чат: фильтр, рецепт и вопрос — по версии подбора
    again = user.post(f"/selections/{old_sel['selection_id']}/filter", {"filters": {"kcal": {"max": 200}}}).json()
    assert again["items"] == old_filtered["items"] and again["total"] == old_filtered["total"]
    rec_old = user.post(f"/selections/{old_sel['selection_id']}/recipe", {"recipe_id": 1}).json()
    assert rec_old["title"] == "Рис с курицей" and rec_old["corpus_version"] == VERSION
    conv = rec_old["conversation_id"]

    r = _delete(admin, 1, VERSION)
    assert r.status_code == 409  # версия записи уже другая
    r = _delete(admin, 1, VERSION + "+admin.1")
    assert r.status_code == 200 and r.json()["corpus_version"] == VERSION + "+admin.2"
    assert _delete(admin, 1, VERSION + "+admin.2").status_code == 404
    _s, ids = _ids(user, "рис")
    assert 1 not in ids
    r = user.post(f"/selections/{old_sel['selection_id']}/filter", {"filters": {}})
    assert 1 in [i["recipe_id"] for i in r.json()["items"]]  # старый подбор видит свою версию
    r = user.post(f"/conversations/{conv}/messages", {"message_id": "after-delete", "text": "Что на шаге 2?"})
    assert r.status_code == 200  # вопрос по снимку после удаления

    r = admin.post("/admin/rag/recipes", NEW)
    assert r.json()["recipe_id"] == 9  # следующий ID; удалённый 1 не переиспользуется
    admin.post("/admin/rag/recipes", {**NEW, "title": "Кумкват 2"})
    r = _delete(admin, 10, VERSION + "+admin.4")
    assert r.status_code == 200
    assert admin.post("/admin/rag/recipes", {**NEW, "title": "Кумкват 3"}).json()["recipe_id"] == 11
    items = admin.get("/admin/activity").json()["items"]  # новые события первыми
    events = {}
    for e in items:
        if e["status"] == "ok":
            events.setdefault(e["event_type"], e)
    conflicts = [e for e in items if e["event_type"] == "rag_update" and e["status"] == "error"]
    assert conflicts and admin.get("/admin/requests/" + conflicts[0]["request_id"]).json()["error_code"] in (
        "VERSION_CONFLICT", "DUPLICATE_RECIPE", "NOT_FOUND")
    assert events["rag_update"]["recipe_id"] == 1 and events["rag_delete"]["count"] == 1
    d = admin.get("/admin/requests/" + events["rag_update"]["request_id"]).json()
    assert [s["name"] for s in d["stages"]][-2:] == ["Подмена индекса", "LLM"] and d["llm_called"] is False
    assert "rev=" in d["index_version"]


def test_restart_replays_changes(client_factory, make_admin, settings, searcher, fake_llm):
    admin = _admin(client_factory, make_admin)
    admin.post("/admin/rag/recipes", NEW)
    item = admin.get("/admin/rag").json()["items"][0]
    assert item["recipe_id"] == 1
    _delete(admin, 2, VERSION)
    _put(admin, 1, {"title": "Рис с шафраном", "url": item["url"],
                    "ingredients": [{"name": "Рис"}, {"name": "Шафран"}], "expected_version": VERSION})
    before = admin.get("/admin/rag?limit=100").json()
    app2 = create_app(settings, search=make_service(build_searcher(), settings.db_path), llm=None)
    from conftest import Api
    api2 = Api(app2)
    email, pw = "root@ai-chef.test", "RootPass123"
    api2.post("/auth/login", {"email": email, "password": pw})
    after = api2.get("/admin/rag?limit=100").json()
    assert [(i["recipe_id"], i["title"], i["corpus_version"]) for i in after["items"]] == \
        [(i["recipe_id"], i["title"], i["corpus_version"]) for i in before["items"]]
    assert after["corpus_version"] == VERSION + "+admin.3"
    _s, ids = _ids(api2, "шафран")
    assert ids == [1]
    _s, ids = _ids(api2, "лук")
    assert 2 not in ids
    assert api2.post("/admin/rag/recipes", {**NEW, "title": "Новый"}).json()["recipe_id"] == 10
    api2.close()


def test_admin_change_uses_search_module_build(client_factory, make_admin, app, monkeypatch):
    """Индекс после изменения собирает модуль поиска (RecipeSearcher.build); при сбое сборки
    ни БД, ни действующий индекс не меняются."""
    admin = _admin(client_factory, make_admin)
    from rag.search import RecipeSearcher
    calls = []
    real_build = RecipeSearcher.build.__func__

    def spy(cls, corpus, *a, **kw):
        calls.append(len(corpus))
        return real_build(cls, corpus, *a, **kw)
    monkeypatch.setattr(RecipeSearcher, "build", classmethod(spy))
    assert admin.post("/admin/rag/recipes", NEW).status_code == 201
    assert calls == [9]

    def broken(cls, corpus, *a, **kw):
        raise MemoryError("no memory")
    monkeypatch.setattr(RecipeSearcher, "build", classmethod(broken))
    before = admin.get("/admin/rag").json()
    r = admin.post("/admin/rag/recipes", {**NEW, "title": "Другое"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "SEARCH_UNAVAILABLE"
    after = admin.get("/admin/rag").json()
    assert after["total"] == before["total"] and after["corpus_version"] == before["corpus_version"]
    _s, ids = _ids(admin, "кумкват")
    assert ids == [9]


def test_concurrent_search_during_writes(client_factory, make_admin, app):
    admin = _admin(client_factory, make_admin)
    errors = []

    def reader():
        cat = app.state.search.catalog
        for _ in range(200):
            try:
                ids, rev, toks = cat.search_ids("курица рис кумкват")
                cat.page(ids, rev, toks, {"kcal": {"min": None, "max": 300}})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for i in range(15):
        assert admin.post("/admin/rag/recipes", {**NEW, "title": f"Кумкват {i}"}).status_code == 201
    for t in threads:
        t.join()
    assert not errors


def test_stale_overlay_blocks_writes_and_cli_export(client_factory, make_admin, settings, tmp_path):
    admin = _admin(client_factory, make_admin)
    admin.post("/admin/rag/recipes", NEW)
    item = admin.get("/admin/rag?offset=1&limit=1").json()["items"][0]
    _put(admin, item["recipe_id"], {"title": "Изменённый", "url": item["url"],
                                    "ingredients": [{"name": "Рис"}, {"name": "Сыр"}], "expected_version": VERSION})
    rebuilt = [dict(r) for r in RECIPES[:6]]  # Александра пересобрала корпус: другая версия и состав
    app2 = create_app(settings, search=make_service(build_searcher(rebuilt, "test-corpus-v2"), settings.db_path), llm=None)
    from conftest import Api
    api2 = Api(app2)
    api2.post("/auth/login", {"email": "root@ai-chef.test", "password": "RootPass123"})
    health = api2.get("/health").json()
    assert health["search"]["catalog"]["stale_admin_changes"] == 2
    lst = api2.get("/admin/rag").json()
    assert lst["total"] == 6 and lst["corpus_version"] == "test-corpus-v2"  # изменения старой базы не применены
    r = api2.post("/admin/rag/recipes", {**NEW, "title": "Другой"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CATALOG_STALE"
    api2.close()

    env = {"CHEF_DB_PATH": str(settings.db_path), "PATH": "/usr/bin:/bin"}
    status = subprocess.run([sys.executable, "-m", "chef_server", "rag-status"], cwd=SERVER, env=env,
                            capture_output=True, text=True, check=True).stdout
    key = status.split("\t")[0]
    assert key.startswith(VERSION + "|test_corpus|8")
    out = tmp_path / "admin.jsonl"
    subprocess.run([sys.executable, "-m", "chef_server", "rag-export", "--base-key", key, "--out", str(out)],
                   cwd=SERVER, env=env, check=True, capture_output=True)
    rows = [json.loads(line) for line in out.read_text("utf-8").splitlines()]
    assert {r["title"] for r in rows} == {"Изменённый", NEW["title"]}
    subprocess.run([sys.executable, "-m", "chef_server", "rag-drop", "--base-key", key], cwd=SERVER, env=env,
                   check=True, capture_output=True)
    app3 = create_app(settings, search=make_service(build_searcher(rebuilt, "test-corpus-v2"), settings.db_path), llm=None)
    api3 = Api(app3)
    api3.post("/auth/login", {"email": "root@ai-chef.test", "password": "RootPass123"})
    r = api3.post("/admin/rag/import", {"text": out.read_text("utf-8")})
    assert r.status_code == 201 and r.json()["added"] == 2  # перенос через обычный импорт
    api3.close()
