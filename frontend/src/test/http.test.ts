import {
  beforeAll,
  beforeEach,
  afterAll,
  afterEach,
  describe,
  it,
  expect,
} from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../mocks/handlers";
import { initializeDemo, readState, setMode, ownerOf } from "../mocks/store";
import { openDB } from "idb";
import { MAX_JSONL_BYTES } from "../lib/rag";
import type { DemoAccess } from "../mocks/store";
const server = setupServer(...handlers);
let access: DemoAccess[] = [];
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(async () => {
  access = await initializeDemo(true);
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
const base = "http://localhost/api/v1";
async function req(
  path: string,
  method = "GET",
  body?: unknown,
  cookie?: string,
) {
  return fetch(base + path, {
    method,
    headers: {
      ...(body ? { "content-type": "application/json" } : {}),
      ...(cookie ? { cookie } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}
async function login(role: "user" | "admin" = "user") {
  const a = access.find((a) => a.role === role)!;
  const r = await req("/auth/login", "POST", {
    email: a.email,
    password: a.password,
  });
  expect(r.status).toBe(200);
  return r.headers.get("set-cookie")!.split(";")[0];
}
describe("HTTP mock contract, not component fixture injection", () => {
  it("rejects anonymous and incorrect credentials", async () => {
    expect((await req("/chats")).status).toBe(401);
    const r = await req("/auth/login", "POST", {
      email: access[0].email,
      password: "WrongPassword",
    });
    expect(r.status).toBe(401);
    expect((await r.json()).error.code).toBe("INVALID_CREDENTIALS");
  });
  it("public registration cannot grant admin; duplicate email is 409", async () => {
    const password = crypto.randomUUID();
    const body = { email: "new@example.test", password };
    expect(
      (await req("/auth/register", "POST", { ...body, role: "admin" })).status,
    ).toBe(400);
    const a = await req("/auth/register", "POST", body);
    expect(a.status).toBe(201);
    expect((await a.json()).role).toBe("user");
    expect((await req("/auth/register", "POST", body)).status).toBe(409);
  });
  it("all administrative endpoints reject user", async () => {
    const cookie = await login();
    for (const p of [
      "/admin/users",
      "/admin/activity",
      "/admin/requests/demo-request-1",
    ])
      expect((await req(p, "GET", undefined, cookie)).status).toBe(403);
    expect(
      (
        await req(
          "/admin/users",
          "POST",
          {
            email: "a@test.test",
            password: crypto.randomUUID(),
            role: "admin",
          },
          cookie,
        )
      ).status,
    ).toBe(403);
  });
  it("admin creates each role and new admin can create admin", async () => {
    const cookie = await login("admin");
    const password = crypto.randomUUID();
    for (const role of ["user", "admin"]) {
      const r = await req(
        "/admin/users",
        "POST",
        { email: role + "@new.test", password, role },
        cookie,
      );
      expect(r.status).toBe(201);
      const data = await r.json();
      expect(data.role).toBe(role);
      expect(data.password).toBeUndefined();
      expect(data.digest).toBeUndefined();
    }
    const response = await req("/auth/login", "POST", {
      email: "admin@new.test",
      password,
    });
    const newCookie = response.headers.get("set-cookie")!.split(";")[0];
    expect(
      (
        await req(
          "/admin/users",
          "POST",
          { email: "third@test.test", password, role: "admin" },
          newCookie,
        )
      ).status,
    ).toBe(201);
    for (const role of ["other", undefined])
      expect(
        (
          await req(
            "/admin/users",
            "POST",
            { email: "bad@test.test", password, role },
            cookie,
          )
        ).status,
      ).toBe(400);
  });
  it("neither user nor admin can read or delete a foreign chat", async () => {
    for (const role of ["user", "admin"] as const) {
      const c = await login(role);
      expect(
        (await req("/chats/demo-other-chat", "GET", undefined, c)).status,
      ).toBe(404);
      expect(
        (await req("/chats/demo-other-chat", "DELETE", undefined, c)).status,
      ).toBe(404);
    }
  });
  it("filters the full selection, not the five shown; includes exact boundary", async () => {
    const c = await login();
    const made = await (
      await req("/selections", "POST", { products_text: "курица рис лук" }, c)
    ).json();
    expect(made.items.find((item: { recipe_id: number }) => item.recipe_id === 1).missing_ingredients).toContain("Вода");
    const r = await req(
      "/selections/" + made.selection_id + "/filter",
      "POST",
      { filters: { kcal: { max: 165 }, max_total_time_minutes: 25 } },
      c,
    );
    expect(r.status).toBe(200);
    expect(
      (await r.json()).items.map((i: { recipe_id: number }) => i.recipe_id),
    ).toEqual([1]);
    expect(
      (
        await req(
          "/selections/" + made.selection_id + "/filter",
          "POST",
          { filters: { kcal: { min: 10, max: 1 } } },
          c,
        )
      ).status,
    ).toBe(400);
  });
  it("preserves history and selected version after logout; duplicate question is idempotent", async () => {
    let c = await login();
    const chat = await (
      await req("/chats/demo-chat-1", "GET", undefined, c)
    ).json();
    const selected = await (
      await req(
        "/selections/" + chat.selection_id + "/recipe",
        "POST",
        { recipe_id: 1 },
        c,
      )
    ).json();
    expect(selected.ingredients).toContainEqual({ name: "Вода", amount: "300 мл" });
    expect(selected.verified_version).toBe("demo-recipes-v2");
    const message_id = crypto.randomUUID();
    for (let i = 0; i < 2; i++)
      expect(
        (
          await req(
            "/conversations/" + selected.conversation_id + "/messages",
            "POST",
            { message_id, text: "Что делать на втором шаге?" },
            c,
          )
        ).status,
      ).toBe(200);
    expect((await req("/auth/logout", "POST", {}, c)).status).toBe(204);
    expect((await req("/chats", "GET", undefined, c)).status).toBe(401);
    c = await login();
    const restored = await (
      await req("/chats/demo-chat-1", "GET", undefined, c)
    ).json();
    expect(restored.selected_recipe.recipe_id).toBe(1);
    expect(restored.selected_recipe.verified_version).toBe(selected.verified_version);
    expect(restored.selected_recipe.corpus_version).toBe("demo-corpus-v1");
    expect(
      restored.messages.filter(
        (m: { message_id: string }) => m.message_id === message_id,
      ),
    ).toHaveLength(1);
  });
  it("deleted chat cannot be resurrected by an in-flight answer", async () => {
    const c = await login();
    const selected = await (
      await req(
        "/selections/selection-demo-chat-1/recipe",
        "POST",
        { recipe_id: 1 },
        c,
      )
    ).json();
    const pending = req(
      "/conversations/" + selected.conversation_id + "/messages",
      "POST",
      { message_id: crypto.randomUUID(), text: "Второй шаг" },
      c,
    );
    expect(
      (await req("/chats/demo-chat-1", "DELETE", undefined, c)).status,
    ).toBe(204);
    expect((await pending).status).toBe(404);
    expect((await req("/chats/demo-chat-1", "GET", undefined, c)).status).toBe(
      404,
    );
  });
  it("provides explicit errors and keeps diagnostics free of conversation text", async () => {
    const c = await login();
    await setMode("search-error");
    const r = await req("/selections", "POST", { products_text: "курица" }, c);
    expect(r.status).toBe(503);
    const s = await readState();
    expect(s.events.some((e) => e.status === "error")).toBe(true);
    expect(JSON.stringify(s.events)).not.toContain("products_text");
    expect(ownerOf(s.chats[0])).toBe("demo-user");
  });
  it("missing steps and unavailable saved context are distinct", async () => {
    const c = await login();
    await setMode("incomplete");
    const r = await req(
      "/selections/selection-demo-chat-1/recipe",
      "POST",
      { recipe_id: 7 },
      c,
    );
    expect(r.status).toBe(409);
    expect((await r.json()).error.code).toBe("RECIPE_INCOMPLETE");
    await setMode("normal");
    const selected = await (
      await req(
        "/selections/selection-demo-chat-1/recipe",
        "POST",
        { recipe_id: 1 },
        c,
      )
    ).json();
    await setMode("unavailable");
    const response = await req(
      "/conversations/" + selected.conversation_id + "/messages",
      "POST",
      { message_id: crypto.randomUUID(), text: "Второй шаг?" },
      c,
    );
    expect(response.status).toBe(409);
    expect((await response.json()).error.code).toBe("RECIPE_UNAVAILABLE");
    expect((await req("/chats/demo-chat-1", "GET", undefined, c)).status).toBe(
      200,
    );
  });
});

const newRecipe = {
  title: "Гречка с грибами",
  ingredients: [{ name: "Гречка" }, { name: "Грибы", amount: "200 г" }],
  url: "https://example.test/grechka",
  steps: ["Сварите гречку.", "Приготовьте грибы и смешайте."],
};
describe("administrative demo RAG", () => {
  it("checks all routes before parsing data for guests and users", async () => {
    const cookie = await login();
    for (const [path, method] of [["/admin/rag", "GET"], ["/admin/rag/recipes", "POST"], ["/admin/rag/import/validate", "POST"], ["/admin/rag/import", "POST"]]) {
      expect((await req(path, method, method === "POST" ? {} : undefined, "chef_session=missing")).status).toBe(401);
      expect((await req(path, method, method === "POST" ? {} : undefined, cookie)).status).toBe(403);
    }
  });
  it("adds a recipe, persists it and supports search, opening, history and unknown parameters", async () => {
    const a = await login("admin");
    const c = await login();
    const old = await (await req("/selections", "POST", { products_text: "гречка и грибы" }, c)).json();
    expect(old.items).toHaveLength(0);
    const added = await req("/admin/rag/recipes", "POST", newRecipe, a);
    expect(added.status).toBe(201);
    const record = await added.json();
    expect(record.recipe_id).toBeGreaterThan(7);
    expect(record.corpus_version).toBe("demo-corpus-v2");
    await initializeDemo();
    const list = await (await req("/admin/rag?limit=1&offset=7", "GET", undefined, a)).json();
    expect(list.total).toBe(8);
    expect(list.items).toHaveLength(1);
    expect(list.items[0]).toMatchObject({ data_mode: "demo", total_time_minutes: null, nutrition_per_100g: { kcal: null }, ingredients: [{ name: "Гречка", amount: null }, { name: "Грибы", amount: "200 г" }] });
    const selection = await (await req("/selections", "POST", { products_text: "ГРЕЧКА, грибы" }, c)).json();
    expect(selection.items[0].recipe_id).toBe(record.recipe_id);
    expect(selection.corpus_version).toBe("demo-corpus-v2");
    const full = await (await req(`/selections/${selection.selection_id}/recipe`, "POST", { recipe_id: record.recipe_id }, c)).json();
    expect(full.steps).toEqual(newRecipe.steps);
    const snapshot = await (await req(`/chats/${selection.chat_id}`, "GET", undefined, c)).json();
    expect(snapshot.selected_recipe.recipe_id).toBe(record.recipe_id);
    expect((await req("/admin/rag/import", "POST", { text: [JSON.stringify({ ...newRecipe, title: "Вторая гречка" }), JSON.stringify({ ...newRecipe, title: "Третья гречка" })].join("\n") }, a)).status).toBe(201);
    const restored = await (await req(`/chats/${selection.chat_id}`, "GET", undefined, c)).json();
    expect(restored.selected_recipe).toEqual(snapshot.selected_recipe);
    expect(restored.selection.corpus_version).toBe("demo-corpus-v2");
    const ids = (await readState()).rag.recipes.map((r) => r.recipe_id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(snapshot).not.toHaveProperty("candidates");
    expect(JSON.stringify(snapshot)).not.toContain('"difficulty"');
    const filtered = await (await req(`/selections/${selection.selection_id}/filter`, "POST", { filters: { kcal: { max: 300 } } }, c)).json();
    expect(filtered.items).toHaveLength(0);
    const oldFiltered = await (await req(`/selections/${old.selection_id}/filter`, "POST", { filters: {} }, c)).json();
    expect(oldFiltered.items).toHaveLength(0);
    expect(oldFiltered.corpus_version).toBe("demo-corpus-v1");
    const diagnostic = await (await req(`/admin/requests/${oldFiltered.request_id}`, "GET", undefined, a)).json();
    expect(diagnostic.corpus_version).toBe("demo-corpus-v1");
    const state = await readState();
    const event = state.events.find((e) => e.event_type === "rag_add");
    expect(event).toMatchObject({ user_id: "demo-admin", count: 1, corpus_version: "demo-corpus-v2" });
    expect(JSON.stringify(state.events)).not.toContain(newRecipe.title);
    await initializeDemo(true);
    expect((await readState()).rag.recipes).toHaveLength(7);
  });
  it("validates line errors, duplicate sets and atomic imports including stale validation", async () => {
    const a = await login("admin");
    const text = [JSON.stringify(newRecipe), "{broken", JSON.stringify({ ...newRecipe, ingredients: [...newRecipe.ingredients].reverse(), title: newRecipe.title.toUpperCase() })].join("\n");
    const report = await (await req("/admin/rag/import/validate", "POST", { text }, a)).json();
    expect(report).toMatchObject({ count: 3, valid: false, errors: [{ line: 2 }], duplicates: [{ line: 3 }] });
    expect((await readState()).rag.revision).toBe(1);
    expect((await req("/admin/rag/import", "POST", { text }, a)).status).toBe(400);
    expect((await readState()).rag.recipes).toHaveLength(7);
    const clean = JSON.stringify({ ...newRecipe, id: 1, source: "example" });
    expect((await (await req("/admin/rag/import/validate", "POST", { text: clean }, a)).json()).valid).toBe(true);
    expect((await req("/admin/rag/import", "POST", { text: clean }, a)).status).toBe(201);
    expect((await req("/admin/rag/import", "POST", { text: clean }, a)).status).toBe(409);
    expect((await req("/admin/rag/recipes", "POST", newRecipe, a)).status).toBe(409);
    expect((await readState()).rag.revision).toBe(2);
    const page = await (await req("/admin/rag?limit=1&offset=7", "GET", undefined, a)).json();
    expect(page.items[0].recipe_id).toBe(8);
  });
  it("rejects oversized, empty, excessive and invalid recipes without writes", async () => {
    const a = await login("admin");
    for (const text of ["", " ", "x".repeat(MAX_JSONL_BYTES + 1), Array(1001).fill(JSON.stringify(newRecipe)).join("\n")]) {
      const report = await (await req("/admin/rag/import/validate", "POST", { text }, a)).json();
      expect(report.valid).toBe(false);
      expect(report.errors.length).toBeGreaterThan(0);
      expect((await req("/admin/rag/import", "POST", { text }, a)).status).toBe(400);
    }
    for (const recipe of [{ ...newRecipe, url: "javascript:alert(1)" }, { ...newRecipe, ingredients: [{ name: "Гречка" }] }, { ...newRecipe, nutrition_per_100g: { kcal: -1 } }, { ...newRecipe, total_time_minutes: 1.5 }, { ...newRecipe, steps: [""] }]) {
      expect((await req("/admin/rag/recipes", "POST", recipe, a)).status).toBe(400);
    }
    expect((await readState()).rag.revision).toBe(1);
    expect((await readState()).rag.recipes).toHaveLength(7);
  });
  it("shows imported incomplete recipes but refuses invented steps", async () => {
    const a = await login("admin");
    const c = await login();
    const { steps: _, ...incomplete } = newRecipe;
    expect((await req("/admin/rag/import", "POST", { text: JSON.stringify(incomplete) }, a)).status).toBe(201);
    const selection = await (await req("/selections", "POST", { products_text: "гречка" }, c)).json();
    expect(selection.items).toHaveLength(1);
    const response = await req(`/selections/${selection.selection_id}/recipe`, "POST", { recipe_id: 8 }, c);
    expect(response.status).toBe(409);
    expect((await response.json()).error).toMatchObject({ code: "RECIPE_INCOMPLETE", source_url: newRecipe.url });
  });
  it("migrates legacy storage without resetting users or snapshots", async () => {
    const cookie = await login();
    await req("/selections/selection-demo-chat-1/recipe", "POST", { recipe_id: 1 }, cookie);
    const db = await openDB("ai-chef-demo", 1);
    const legacy = await db.get("kv", "state");
    delete legacy.rag;
    legacy.chats.forEach((c: { candidates?: unknown }) => { delete c.candidates; });
    legacy.chats[0].selected_recipe.difficulty = "easy";
    legacy.chats[0].selected_recipe.provenance.difficulty = { source_ref: "legacy" };
    await db.put("kv", legacy, "state");
    await initializeDemo();
    const restored = await (await req("/chats/demo-chat-1", "GET", undefined, cookie)).json();
    expect(restored.selected_recipe.recipe_id).toBe(1);
    expect(restored.messages).toHaveLength(legacy.chats[0].messages.length);
    expect(JSON.stringify(restored)).not.toContain('"difficulty"');
    expect((await readState()).rag.revision).toBe(1);
  });
  it("treats comma and standalone и equivalently and rejects only separators", async () => {
    const c = await login();
    const results = [];
    for (const products_text of ["курица, рис, лук", "курица и рис и лук", " КУРИЦА, рис и лук "]) {
      const selection = await (await req("/selections", "POST", { products_text }, c)).json();
      results.push(selection.items);
    }
    expect(results[1]).toEqual(results[0]);
    expect(results[2]).toEqual(results[0]);
    const before = (await readState()).chats.length;
    expect((await req("/selections", "POST", { products_text: ", и , И ," }, c)).status).toBe(400);
    expect((await readState()).chats).toHaveLength(before);
  });
});


describe("editing and deleting demo RAG recipes", () => {
  it("authorizes both methods before validation", async () => {
    const c = await login();
    for (const method of ["PUT", "DELETE"]) {
      expect((await req("/admin/rag/recipes/1", method, {}, "chef_session=missing")).status).toBe(401);
      expect((await req("/admin/rag/recipes/1", method, {}, c)).status).toBe(403);
    }
  });
  it("updates all fields, clears omitted values and rejects stale, invalid and duplicate changes atomically", async () => {
    const a = await login("admin");
    const original = (await readState()).rag.recipes[0];
    const changed = { ...newRecipe, description: "Описание", nutrition_per_100g: { kcal: 100, protein_g: 3, fat_g: 2, carbs_g: 16 }, total_time_minutes: 20, expected_version: original.corpus_version };
    const r = await req("/admin/rag/recipes/1", "PUT", changed, a);
    expect(r.status).toBe(200);
    expect(await r.json()).toMatchObject({ recipe_id: 1, corpus_version: "demo-corpus-v2" });
    const edited = (await readState()).rag.recipes[0];
    expect(edited).toMatchObject({ recipe_id: 1, title: changed.title, ingredients: [{ name: "Гречка", amount: null }, { name: "Грибы", amount: "200 г" }], description: changed.description, nutrition_per_100g: changed.nutrition_per_100g, total_time_minutes: 20, steps: changed.steps, url: changed.url, data_mode: "demo", verified_version: "demo-recipes-v2" });
    const before = (await readState()).rag;
    expect((await req("/admin/rag/recipes/1", "PUT", changed, a)).status).toBe(409);
    expect((await (await req("/admin/rag/recipes/1", "DELETE", { expected_version: "demo-corpus-v1" }, a)).json()).error.code).toBe("VERSION_CONFLICT");
    expect((await req("/admin/rag/recipes/1", "PUT", { ...changed, title: "", expected_version: edited.corpus_version }, a)).status).toBe(400);
    const second = (await readState()).rag.recipes[1];
    expect((await (await req("/admin/rag/recipes/1", "PUT", { ...second, expected_version: edited.corpus_version }, a)).json()).error.code).toBe("DUPLICATE_RECIPE");
    expect((await req("/admin/rag/recipes/1", "DELETE", {}, a)).status).toBe(400);
    expect((await readState()).rag).toEqual(before);
    const { steps: _, ...minimal } = newRecipe;
    expect((await req("/admin/rag/recipes/1", "PUT", { ...minimal, expected_version: edited.corpus_version }, a)).status).toBe(200);
    const cleared = (await readState()).rag.recipes[0];
    expect(cleared).toMatchObject({ steps: [], description: null, total_time_minutes: null, nutrition_per_100g: { kcal: null, protein_g: null, fat_g: null, carbs_g: null } });
    const event = (await readState()).events.find((e) => e.event_type === "rag_update");
    expect(event).toMatchObject({ recipe_id: 1, count: 1, user_id: "demo-admin", corpus_version: "demo-corpus-v2" });
    expect(JSON.stringify((await readState()).events)).not.toContain(changed.description);
  });
  it("preserves old selection, recipe, answers and version across editing and deletion", async () => {
    const a = await login("admin");
    const c = await login();
    const old = await (await req("/selections", "POST", { products_text: "курица и рис" }, c)).json();
    const selected = await (await req(`/selections/${old.selection_id}/recipe`, "POST", { recipe_id: 1 }, c)).json();
    const changed = await (await req("/admin/rag/recipes/1", "PUT", { ...newRecipe, expected_version: "demo-corpus-v1" }, a)).json();
    const fresh = await (await req("/selections", "POST", { products_text: "гречка" }, c)).json();
    expect(fresh.items[0]).toMatchObject({ recipe_id: 1, title: newRecipe.title });
    expect((await req("/admin/rag/recipes/1", "DELETE", { expected_version: changed.corpus_version }, a)).status).toBe(200);
    await initializeDemo();
    const missing = await (await req("/selections", "POST", { products_text: "гречка" }, c)).json();
    expect(missing.items).toEqual([]);
    const restored = await (await req(`/chats/${old.chat_id}`, "GET", undefined, c)).json();
    expect(restored.selected_recipe.steps).toEqual(selected.steps);
    expect(restored.selection.corpus_version).toBe("demo-corpus-v1");
    const filtered = await (await req(`/selections/${old.selection_id}/filter`, "POST", { filters: {} }, c)).json();
    expect(filtered.items.some((r: { recipe_id: number }) => r.recipe_id === 1)).toBe(true);
    const answer = await req(`/conversations/${selected.conversation_id}/messages`, "POST", { message_id: crypto.randomUUID(), text: "Второй шаг" }, c);
    expect(answer.status).toBe(200);
    expect((await answer.json()).answer).toBe(selected.steps[1]);
    for (const method of ["PUT", "DELETE"]) expect((await req("/admin/rag/recipes/1", method, { ...newRecipe, expected_version: changed.corpus_version }, a)).status).toBe(404);
    const event = (await readState()).events.find((e) => e.event_type === "rag_delete");
    expect(event).toMatchObject({ recipe_id: 1, user_id: "demo-admin", count: 1, corpus_version: "demo-corpus-v3" });
  });
  it("never reuses deleted IDs, persists changes and restores all fixtures on reset", async () => {
    const a = await login("admin");
    const added = await (await req("/admin/rag/recipes", "POST", newRecipe, a)).json();
    await req(`/admin/rag/recipes/${added.recipe_id}`, "DELETE", { expected_version: added.corpus_version }, a);
    await initializeDemo();
    const next = await (await req("/admin/rag/recipes", "POST", newRecipe, a)).json();
    expect(next.recipe_id).toBeGreaterThan(added.recipe_id);
    for (const r of (await readState()).rag.recipes) expect((await req(`/admin/rag/recipes/${r.recipe_id}`, "DELETE", { expected_version: r.corpus_version }, a)).status).toBe(200);
    expect((await (await req("/admin/rag", "GET", undefined, a)).json()).total).toBe(0);
    await initializeDemo(true);
    expect((await readState()).rag.recipes).toHaveLength(7);
    expect((await readState()).rag.next_id).toBe(8);
  });
  it("migrates the counter using retained snapshots and makes the incomplete fixture editable", async () => {
    const a = await login("admin");
    const c = await login();
    const db = await openDB("ai-chef-demo", 1);
    const state = await db.get("kv", "state");
    delete state.rag.next_id;
    state.chats[0].candidates.push({ ...state.rag.recipes[0], recipe_id: 100 });
    await db.put("kv", state, "state");
    await initializeDemo();
    const added = await (await req("/admin/rag/recipes", "POST", newRecipe, a)).json();
    expect(added.recipe_id).toBe(101);
    const updated = await req("/admin/rag/recipes/7", "PUT", { ...newRecipe, title: "Новая гречка", expected_version: "demo-corpus-v1" }, a);
    expect(updated.status).toBe(200);
    const selection = await (await req("/selections", "POST", { products_text: "гречка" }, c)).json();
    expect(selection.items.some((r: { recipe_id: number }) => r.recipe_id === 7)).toBe(true);
  });
});
