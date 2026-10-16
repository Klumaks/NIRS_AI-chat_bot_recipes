"""Подбор, фильтры, рецепт, вопросы к LLM, история и удаление (SC-03..SC-08, SC-11, SC-12)."""
from __future__ import annotations

import httpx
from conftest import db_dump

from chef_server.llm import build_messages, parse_answer


def _start(api, text="Есть курица, рис и лук"):
    r = api.post("/selections", {"products_text": text})
    assert r.status_code == 201, r.text
    return r.json()


def _choose(api, sel, recipe_id=1):
    r = api.post(f"/selections/{sel['selection_id']}/recipe", {"recipe_id": recipe_id})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------ подбор
def test_selection_cards_and_validation(client_factory):
    api = client_factory()
    api.register_login("cook@test.ru")
    assert api.post("/selections", {"products_text": "   "}).status_code == 400
    assert api.post("/selections", {"products_text": "x" * 2001}).status_code == 400
    r = api.post("/selections", {"products_text": "что приготовить"})  # после предобработки термов нет
    assert r.status_code == 400 and "продукты" in r.json()["error"]["message"]
    sel = _start(api)
    assert sel["chat_id"] and sel["selection_id"] and sel["filters"] == {}
    assert sel["corpus_version"] == "test-corpus-v1" and len(sel["items"]) == 5 and sel["total"] == 8
    card = sel["items"][0]
    assert card["recipe_id"] == 1 and card["data_mode"] == "verified" and "difficulty" not in card
    assert set(card["nutrition_per_100g"]) == {"kcal", "protein_g", "fat_g", "carbs_g"}
    assert "id" not in card and "score" not in card
    assert card["provenance"]["kcal"]["method"] == "calculation"
    assert card["provenance"]["total_time_minutes"]["method"] == "source"
    plov = next(i for i in sel["items"] if i["recipe_id"] == 3)
    assert plov["nutrition_per_100g"]["kcal"] is None and "kcal" not in plov["provenance"]  # null, не 0
    assert "Морковь" in plov["missing_ingredients"]


def test_empty_result_is_success(client_factory):
    api = client_factory()
    api.register_login("empty@test.ru")
    sel = _start(api, "ананас")
    assert sel["items"] == [] and sel["total"] == 0
    chat = api.get("/chats/" + sel["chat_id"]).json()
    assert "Не нашёл" in chat["messages"][-1]["text"]


def test_search_failure_is_503_and_logged(client_factory, app, make_admin, monkeypatch):
    api = client_factory()
    api.register_login("fail@test.ru")

    def broken(_text):
        raise RuntimeError("index unavailable")
    monkeypatch.setattr(app.state.search.catalog, "search_ids", broken)
    r = api.post("/selections", {"products_text": "курица"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "SEARCH_UNAVAILABLE"
    assert api.get("/chats").json()["total"] == 0  # чат при сбое не создан
    email, pw = make_admin()
    admin = client_factory()
    admin.post("/auth/login", {"email": email, "password": pw})
    ev = next(e for e in admin.get("/admin/activity").json()["items"] if e["event_type"] == "search")
    assert ev["status"] == "error"
    assert admin.get("/admin/requests/" + ev["request_id"]).json()["error_code"] == "SEARCH_UNAVAILABLE"


# ------------------------------------------------------------------------------ фильтры
def test_filters_bounds_null_whole_selection_and_reset(client_factory):
    api = client_factory()
    api.register_login("filter@test.ru")
    sel = _start(api)
    sid = sel["selection_id"]
    r = api.post(f"/selections/{sid}/filter", {"filters": {"max_total_time_minutes": 30}})
    ids = [i["recipe_id"] for i in r.json()["items"]]
    assert r.status_code == 200 and 1 in ids and 2 not in ids  # 30 включается, 31 — нет
    assert 3 not in ids  # неизвестное время исключается при активном ограничении
    # фильтр по всему подбору: рецепт 8 не входил в первые пять, но проходит фильтр
    assert 8 not in [i["recipe_id"] for i in sel["items"]] and 8 in ids
    r = api.post(f"/selections/{sid}/filter", {"filters": {"kcal": {"min": 150, "max": 180}, "protein_g": {"min": 10}}})
    assert sorted(i["recipe_id"] for i in r.json()["items"]) == [1, 2, 8] and r.json()["total"] == 3
    for bad in ({"kcal": {"min": 200, "max": 100}}, {"kcal": {"min": -1}}, {"max_total_time_minutes": 0},
                {"max_total_time_minutes": 2.5}, {"sugar": {"max": 1}}, {"kcal": {"lo": 1}}, {"kcal": {"max": "5"}}):
        assert api.post(f"/selections/{sid}/filter", {"filters": bad}).status_code == 400, bad
    assert api.post(f"/selections/{sid}/filter", {}).status_code == 400
    r = api.post(f"/selections/{sid}/filter", {"filters": {"kcal": {"max": 1}}})
    assert r.json()["items"] == [] and r.json()["total"] == 0
    r = api.post(f"/selections/{sid}/filter", {"filters": {}})
    assert r.json()["total"] == 8 and r.json()["filters"] == {}
    api.post(f"/selections/{sid}/filter", {"filters": {"kcal": {"min": None, "max": 160}}})
    chat = api.get("/chats/" + sel["chat_id"]).json()
    assert chat["filters"] == {"kcal": {"min": None, "max": 160}} and chat["selection"]["filters"] == chat["filters"]


# ------------------------------------------------------------------------------ рецепт
def test_recipe_selection_and_incomplete(client_factory):
    api = client_factory()
    api.register_login("recipe@test.ru")
    sel = _start(api, "рис")
    assert api.post(f"/selections/{sel['selection_id']}/recipe", {"recipe_id": 999}).status_code == 404
    assert api.post(f"/selections/{sel['selection_id']}/recipe", {"recipe_id": "1"}).status_code == 400
    r = api.post(f"/selections/{sel['selection_id']}/recipe", {"recipe_id": 4})
    assert r.status_code == 409 and r.json()["error"]["code"] == "RECIPE_INCOMPLETE"
    assert r.json()["error"]["source_url"] == "https://example.test/r/4"
    rec = _choose(api, sel, 1)
    assert rec["recipe_id"] == 1 and rec["steps"][0] == "Нарезать курицу и лук."
    assert rec["ingredients"][3] == {"name": "Вода", "amount": "300 мл"}
    assert rec["corpus_version"] == "test-corpus-v1" and rec["conversation_id"] and rec["chat_id"] == sel["chat_id"]
    assert rec["provenance"]["steps"]["method"] == "source" and rec["verified_version"]


# ------------------------------------------------------------------------------ вопросы и LLM
def test_question_answer_sources_and_prompt(client_factory, fake_llm):
    api = client_factory()
    api.register_login("ask@test.ru")
    sel = _start(api)
    rec = _choose(api, sel, 1)
    conv = rec["conversation_id"]
    r = api.post(f"/conversations/{conv}/messages", {"message_id": "m1", "text": "Что делать на втором шаге?"})
    assert r.status_code == 200, r.text
    ans = r.json()
    assert ans["status"] == "answered" and ans["message_id"] == "m1" and ans["chat_id"] == sel["chat_id"]
    assert ans["sources"] == [{"recipe_id": 1, "url": "https://example.test/r/1", "step_numbers": [2]}]  # 99 отброшен
    req = fake_llm.requests[-1]
    assert req["headers"]["authorization"] == "Bearer secret-key"
    assert req["body"]["model"] == "test-model" and req["body"]["response_format"] == {"type": "json_object"}
    system = req["body"]["messages"][0]["content"]
    assert "2. Обжарить 10 минут." in system and "Вода: 300 мл" in system and "не выдумывай" in system.lower()
    assert req["body"]["messages"][-1] == {"role": "user", "content": "Что делать на втором шаге?"}
    # повтор того же message_id не дублирует вопрос и не вызывает модель снова
    calls = len(fake_llm.requests)
    again = api.post(f"/conversations/{conv}/messages", {"message_id": "m1", "text": "Что делать на втором шаге?"})
    assert again.json()["answer"] == ans["answer"] and len(fake_llm.requests) == calls
    msgs = api.get("/chats/" + sel["chat_id"]).json()["messages"]
    assert sum(m["message_id"] == "m1" for m in msgs) == 1
    # вторая реплика получает историю ветки
    fake_llm.reply = {"status": "insufficient_context", "answer": "В рецепте нет температуры.", "step_numbers": []}
    r = api.post(f"/conversations/{conv}/messages", {"message_id": "m2", "text": "Какая температура?"})
    assert r.json()["status"] == "insufficient_context" and r.json()["sources"] == []
    roles = [m["role"] for m in fake_llm.requests[-1]["body"]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    # ключ не попадает в журнал и диагностику
    assert "secret-key" not in str(api.get("/chats/" + sel["chat_id"]).json())


def test_llm_failure_then_retry_without_duplicate(client_factory, fake_llm, settings):
    api = client_factory()
    api.register_login("retry@test.ru")
    sel = _start(api)
    conv = _choose(api, sel, 1)["conversation_id"]
    fake_llm.raise_exc = httpx.ConnectError("down")
    r = api.post(f"/conversations/{conv}/messages", {"message_id": "q1", "text": "Сколько варить рис?"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "LLM_UNAVAILABLE"
    chat = api.get("/chats/" + sel["chat_id"]).json()
    assert chat["selected_recipe"]["recipe_id"] == 1  # рецепт доступен после сбоя
    assert not any(m["message_id"] == "q1" for m in chat["messages"])
    fake_llm.raise_exc = None
    fake_llm.status_code = 500
    assert api.post(f"/conversations/{conv}/messages", {"message_id": "q1", "text": "Сколько варить рис?"}).status_code == 503
    fake_llm.status_code = 200
    r = api.post(f"/conversations/{conv}/messages", {"message_id": "q1", "text": "Сколько варить рис?"})
    assert r.status_code == 200
    msgs = api.get("/chats/" + sel["chat_id"]).json()["messages"]
    assert sum(m["message_id"] == "q1" for m in msgs) == 1
    dump = db_dump(settings)
    assert "LLM_UNAVAILABLE:LLM_CONNECTION" in dump and "LLM_UNAVAILABLE:LLM_HTTP_500" in dump
    assert "Сколько варить рис?" not in dump and fake_llm.reply["answer"] not in dump


def test_llm_not_configured(client_factory, app):
    app.state.llm.provider = "none"
    api = client_factory()
    api.register_login("nollm@test.ru")
    sel = _start(api)
    conv = _choose(api, sel, 1)["conversation_id"]
    r = api.post(f"/conversations/{conv}/messages", {"message_id": "a", "text": "Шаг 1?"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "LLM_UNAVAILABLE"


def test_json_mode_fallback_and_plain_text(client_factory, fake_llm):
    api = client_factory()
    api.register_login("plain@test.ru")
    sel = _start(api)
    conv = _choose(api, sel, 1)["conversation_id"]
    fake_llm.reject_json_mode = True
    fake_llm.reply = "Смотрите шаг 3: добавьте рис и воду."
    r = api.post(f"/conversations/{conv}/messages", {"message_id": "p1", "text": "Когда добавить рис?"})
    assert r.status_code == 200 and r.json()["sources"][0]["step_numbers"] == [3]
    assert "response_format" not in fake_llm.requests[-1]["body"]


def test_switching_recipe_separates_branches(client_factory, fake_llm):
    api = client_factory()
    api.register_login("switch@test.ru")
    sel = _start(api)
    first = _choose(api, sel, 1)["conversation_id"]
    api.post(f"/conversations/{first}/messages", {"message_id": "f1", "text": "Вопрос про рис с курицей"})
    second = _choose(api, sel, 2)["conversation_id"]
    assert second != first
    r = api.post(f"/conversations/{first}/messages", {"message_id": "f2", "text": "Ещё про старое"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "RECIPE_UNAVAILABLE"
    api.post(f"/conversations/{second}/messages", {"message_id": "s1", "text": "Как запечь?"})
    body = fake_llm.requests[-1]["body"]
    assert "Курица с луком" in body["messages"][0]["content"]
    assert "Вопрос про рис с курицей" not in str(body["messages"])  # старая ветка не смешивается
    chat = api.get("/chats/" + sel["chat_id"]).json()
    assert chat["conversation_id"] == second and chat["selected_recipe"]["recipe_id"] == 2
    assert any(m["message_id"] == "f1" and m["conversation_id"] == first for m in chat["messages"])


def test_context_budget_keeps_recipe_and_question():
    recipe = {"title": "Т", "ingredients": [], "steps": ["Шаг"], "url": "u", "nutrition_per_100g": {}}
    history = [{"role": "user", "text": "старое " * 200}, {"role": "assistant", "text": "новое"}]
    base = len(build_messages(recipe, [], "вопрос", 10 ** 6, 0)[0]["content"]) + len("вопрос")
    msgs = build_messages(recipe, history, "вопрос", budget_chars=base + 100, max_history=10)
    assert msgs[0]["role"] == "system" and "РЕЦЕПТ" in msgs[0]["content"]
    assert msgs[-1]["content"] == "вопрос" and [m["content"] for m in msgs[1:-1]] == ["новое"]
    assert parse_answer('```json\n{"status":"answered","answer":"Ок","step_numbers":["1",5]}\n```', 2) == (
        "answered", "Ок", [1])


# ------------------------------------------------------------------------------ история и доступ
def test_history_persists_and_isolated(client_factory, make_admin):
    a = client_factory()
    a.register_login("a@test.ru")
    sel = _start(a)
    a.post(f"/selections/{sel['selection_id']}/filter", {"filters": {"kcal": {"max": 200}}})
    conv = _choose(a, sel, 1)["conversation_id"]
    a.post(f"/conversations/{conv}/messages", {"message_id": "h1", "text": "Вопрос"})
    second = _start(a, "рис")  # новый подбор — отдельный чат, старый сохранён
    a.post("/auth/logout")
    assert a.post("/auth/login", {"email": "a@test.ru", "password": "Password123"}).status_code == 200
    chats = a.get("/chats").json()
    assert chats["total"] == 2 and chats["items"][0]["chat_id"] == second["chat_id"]
    assert chats["items"][1]["title"] == "Есть курица, рис и лук"
    chat = a.get("/chats/" + sel["chat_id"]).json()
    assert chat["products_text"] == "Есть курица, рис и лук" and chat["filters"] == {"kcal": {"min": None, "max": 200}}
    assert chat["selected_recipe"]["recipe_id"] == 1 and chat["conversation_id"] == conv
    assert chat["resume_status"] == "ready" and [m["message_id"] for m in chat["messages"]].count("h1") == 1
    assert len(chat["selection"]["items"]) >= 1

    b = client_factory()
    b.register_login("b@test.ru")
    assert b.get("/chats").json()["total"] == 0
    for call in (lambda: b.get("/chats/" + sel["chat_id"]),
                 lambda: b.delete("/chats/" + sel["chat_id"]),
                 lambda: b.post(f"/selections/{sel['selection_id']}/filter", {"filters": {}}),
                 lambda: b.post(f"/selections/{sel['selection_id']}/recipe", {"recipe_id": 1}),
                 lambda: b.post(f"/conversations/{conv}/messages", {"message_id": "x", "text": "?"})):
        r = call()
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    email, pw = make_admin()
    admin = client_factory()
    admin.post("/auth/login", {"email": email, "password": pw})
    assert admin.get("/chats/" + sel["chat_id"]).status_code == 404  # роль admin не даёт чужие чаты
    assert a.get("/chats/" + sel["chat_id"]).status_code == 200  # чат цел после попыток


def test_delete_chat_and_late_answer(client_factory, fake_llm, settings):
    api = client_factory()
    api.register_login("del@test.ru")
    keep = _start(api, "рис")
    sel = _start(api)
    conv = _choose(api, sel, 1)["conversation_id"]
    # пока модель отвечает, чат удаляют: ответ не должен восстановить чат
    fake_llm.on_call = lambda: api.delete("/chats/" + sel["chat_id"])
    r = api.post(f"/conversations/{conv}/messages", {"message_id": "late", "text": "Ответишь?"})
    fake_llm.on_call = None
    assert r.status_code == 404
    assert api.get("/chats/" + sel["chat_id"]).status_code == 404
    assert api.post(f"/selections/{sel['selection_id']}/filter", {"filters": {}}).status_code == 404
    assert api.delete("/chats/" + sel["chat_id"]).status_code == 404
    ids = [c["chat_id"] for c in api.get("/chats").json()["items"]]
    assert ids == [keep["chat_id"]]
    from chef_server.db import connect
    conn = connect(settings.db_path)
    left = conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (sel["chat_id"],)).fetchone()[0]
    left += conn.execute("SELECT COUNT(*) FROM conversations WHERE chat_id = ?", (sel["chat_id"],)).fetchone()[0]
    left += conn.execute("SELECT COUNT(*) FROM selections WHERE chat_id = ?", (sel["chat_id"],)).fetchone()[0]
    conn.close()
    assert left == 0
    r = api.delete("/chats/" + keep["chat_id"])
    assert r.status_code == 204 and r.content == b""


def test_base_corpus_rebuild_keeps_snapshot_questions(client_factory, app, settings, fake_llm):
    """Пересборка корпуса Александры: старый подбор нельзя продолжить, вопросы идут по снимку рецепта."""
    from conftest import build_searcher, make_service
    api = client_factory()
    api.register_login("ver@test.ru")
    sel = _start(api)
    conv = _choose(api, sel, 1)["conversation_id"]
    api.post(f"/conversations/{conv}/messages", {"message_id": "v1", "text": "Вопрос"})
    app.state.search = make_service(build_searcher(version="test-corpus-v2"), settings.db_path)
    chat = api.get("/chats/" + sel["chat_id"]).json()
    assert chat["resume_status"] == "ready" and chat["selected_recipe"]["corpus_version"] == "test-corpus-v1"
    assert any(m["message_id"] == "v1" for m in chat["messages"])
    r = api.post(f"/conversations/{conv}/messages", {"message_id": "v2", "text": "Ещё"})
    assert r.status_code == 200  # снимок самодостаточен: вопросы продолжаются
    r = api.post(f"/selections/{sel['selection_id']}/filter", {"filters": {}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "RECIPE_UNAVAILABLE"
    r = api.post(f"/selections/{sel['selection_id']}/recipe", {"recipe_id": 2})
    assert r.status_code == 409  # старый ID не связывается с другой версией корпуса
    new = _start(api)  # новый подбор работает на новой версии
    assert new["corpus_version"] == "test-corpus-v2"


def test_journal_has_no_texts_or_secrets(client_factory, make_admin, settings, fake_llm):
    api = client_factory()
    api.register_login("secret@test.ru", "VerySecret123")
    sel = _start(api, "Есть курица, рис, лук и уникальный_продукт_42")
    conv = _choose(api, sel, 1)["conversation_id"]
    api.post(f"/conversations/{conv}/messages", {"message_id": "s", "text": "уникальный_вопрос_77"})
    email, pw = make_admin()
    admin = client_factory()
    admin.post("/auth/login", {"email": email, "password": pw})
    q = next(e for e in admin.get("/admin/activity").json()["items"] if e["event_type"] == "question")
    d = admin.get("/admin/requests/" + q["request_id"]).json()
    assert d["llm_called"] is True and d["model"].startswith("test-model") and d["selected_recipe_id"] == 1
    assert [s["name"] for s in d["stages"]][-2:] == ["LLM", "Сохранение вопроса и ответа"]
    dump = db_dump(settings) + str(admin.get("/admin/activity").json())
    for leaked in ("уникальный_продукт_42", "уникальный_вопрос_77", fake_llm.reply["answer"], "VerySecret123",
                   "secret-key", api.c.cookies.get("chef_session")):
        assert leaked not in dump
