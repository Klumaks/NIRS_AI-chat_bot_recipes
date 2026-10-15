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
