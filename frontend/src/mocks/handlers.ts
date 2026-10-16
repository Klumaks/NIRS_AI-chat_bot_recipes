import { http, HttpResponse, delay } from "msw";
import type {
  Filters,
  Role,
  Chat,
  Recipe,
  Diagnostic,
  Activity,
  User,
  SelectedRecipe,
} from "../api/types";
import { ragRecipeSchema, recipeKey, validateJsonl } from "../lib/rag";
import type { RagRecipeInput } from "../lib/rag";
import { API_BASE } from "../api/client";
import { credentialsSchema, userSchema, filtersSchema } from "../lib/forms";
import { matchesFilters, validateFilters } from "../lib/filters";
import { candidates, ingredientTerms } from "./fixtures";
import {
  readState,
  updateState,
  makeUser,
  digest,
  publicUser,
  uid,
  now,
  ownerOf,
  seedChat,
  corpusVersion,
} from "./store";
import type { MockState, StoredUser, OwnedChat } from "./store";
class Fault extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public source_url?: string,
  ) {
    super(message);
  }
}
const fail = (
  status: number,
  code: string,
  message: string,
  source?: string,
): never => {
  throw new Fault(status, code, message, source);
};
function user(
  s: MockState,
  cookies: Record<string, string | undefined>,
): StoredUser {
  const id = s.sessions[cookies.chef_session || ""];
  return (
    s.users.find((u) => u.user_id === id) ||
    fail(401, "AUTH_REQUIRED", "Войдите в аккаунт, чтобы продолжить.")
  );
}
function admin(s: MockState, cookies: Record<string, string | undefined>) {
  const u = user(s, cookies);
  if (u.role !== "admin")
    fail(403, "FORBIDDEN", "Этот раздел доступен только администратору.");
  return u;
}
function owned(
  s: MockState,
  cookies: Record<string, string | undefined>,
  test: (c: Chat) => boolean,
) {
  const u = user(s, cookies);
  return (
    s.chats.find((c) => ownerOf(c) === u.user_id && test(c)) ||
    fail(404, "NOT_FOUND", "Чат не найден или недоступен.")
  );
}
function json<T extends object>(
  data: T,
  rid: string,
  status = 200,
  headers?: HeadersInit,
) {
  return HttpResponse.json({ ...data, request_id: rid }, { status, headers });
}
async function body(req: Request): Promise<Record<string, unknown>> {
  try {
    const value: unknown = await req.json();
    if (!value || typeof value !== "object" || Array.isArray(value))
      return fail(400, "VALIDATION_ERROR", "Передайте JSON-объект.");
    return value as Record<string, unknown>;
  } catch {
    return fail(400, "VALIDATION_ERROR", "Некорректный JSON запроса.");
  }
}
function event(
  s: MockState,
  u: User,
  type: string,
  rid: string,
  ids: number[] = [],
  selected: number | null = null,
  llm = false,
  error: string | null = null,
  version: string = corpusVersion(s),
) {
  const entry: Activity = {
    occurred_at: now(),
    user_id: u.user_id,
    event_type: type,
    status: error ? "error" : "ok",
    duration_ms: llm ? 200 : 20,
    request_id: rid,
  };
  s.events = s.events
    .filter(
      (e) => new Date(e.occurred_at).getTime() > Date.now() - 30 * 86400000,
    )
    .concat(entry);
  const stages: Diagnostic["stages"] =
    type === "search"
      ? [
          { name: "Предобработка (демо)", status: "ok", duration_ms: 2 },
          {
            name: "Поиск по фикстурам",
            status: error ? "error" : "ok",
            duration_ms: 8,
          },
          { name: "Проверенные данные (демо)", status: "ok", duration_ms: 3 },
          { name: "Фильтры", status: "ok", duration_ms: 1 },
        ]
      : [
          {
            name:
              type === "question"
                ? "Контекст выбранного рецепта"
                : "Обработка " + type,
            status: "ok",
            duration_ms: 4,
          },
        ];
  stages.push({
    name: "LLM",
    status: llm ? (error ? "error" : "ok") : "not_run",
    duration_ms: llm ? 190 : null,
  });
  s.diagnostics[rid] = {
    request_id: rid,
    corpus_version:
      type === "login" || type === "register" ? null : version,
    index_version: null,
    normalization_mode: "demo (не BM25)",
    candidate_ids: ids,
    selected_recipe_id: selected,
    llm_called: llm,
    model: llm ? "Имитация ответа — без вызова модели" : null,
    error_code: error,
    stages,
  };
}
function selection(c: Chat, source: Recipe[]) {
  const items = source.filter((r) => matchesFilters(r, c.filters));
  return {
    ...c.selection,
    chat_id: c.chat_id,
    filters: c.filters,
    items: items.slice(0, 5),
    total: items.length,
  };
}
function source(s: MockState, c: Chat) {
  if (s.mode === "empty") return [];
  const base = (c as OwnedChat).candidates ?? candidates(c.products_text, s.rag.recipes);
  const demo = (c as OwnedChat).demo_fixtures ?? [];
  if (s.mode === "unknown") return structuredClone(demo.filter((r) => r.recipe_id === 5));
  if (s.mode === "incomplete") return structuredClone(demo.filter((r) => r.recipe_id === 7));
  return base;
}
type Resolver = (
  req: Request,
  cookies: Record<string, string | undefined>,
  rid: string,
) => Promise<Response>;
function route(method: "get" | "post" | "put" | "delete", path: string, fn: Resolver) {
  return http[method](API_BASE + path, async ({ request, cookies }) => {
    const rid = uid();
    await delay(120);
    try {
      return await fn(request, cookies, rid);
    } catch (e) {
      if (e instanceof Fault)
        return HttpResponse.json(
          {
            request_id: rid,
            error: {
              code: e.code,
              message: e.message,
              ...(e.source_url ? { source_url: e.source_url } : {}),
            },
          },
          { status: e.status },
        );
      console.error("Mock handler failure", e);
      return HttpResponse.json(
        {
          request_id: rid,
          error: {
            code: "MOCK_ERROR",
            message: "Ошибка демонстрационного сервиса.",
          },
        },
        { status: 500 },
      );
    }
  });
}
const resource = (req: Request, segment: string) =>
  decodeURIComponent(
    new URL(req.url).pathname.split(segment)[1]?.split("/")[0] || "",
  );
function addRagRecords(s: MockState, records: RagRecipeInput[], u: User, rid: string, type: "rag_add" | "rag_import" | "rag_update", replaceId?: number) {
  const nextId = replaceId ?? s.rag.next_id;
  if (replaceId == null) s.rag.next_id += records.length;
  s.rag.revision++;
  const version = corpusVersion(s);
  const added: SelectedRecipe[] = records.map((r, i) => ({
    recipe_id: nextId + i,
    title: r.title,
    url: r.url,
    ingredients: r.ingredients.map((ingredient) => ({ ...ingredient, amount: ingredient.amount ?? null })),
    description: r.description ?? null,
    steps: r.steps ?? [],
    nutrition_per_100g: {
      kcal: r.nutrition_per_100g?.kcal ?? null,
      protein_g: r.nutrition_per_100g?.protein_g ?? null,
      fat_g: r.nutrition_per_100g?.fat_g ?? null,
      carbs_g: r.nutrition_per_100g?.carbs_g ?? null,
    },
    total_time_minutes: r.total_time_minutes ?? null,
    corpus_version: version,
    verified_version: `demo-recipes-v${s.rag.revision}`,
    data_mode: "demo",
    missing_ingredients: [],
    provenance: Object.fromEntries(["description", "steps", "kcal", "protein_g", "fat_g", "carbs_g", "total_time_minutes"].map((key) => [key, {
      source_ref: r.url,
      method: "editorial",
      checked_by: "Ввод администратора в демо — не проверенный источник",
      checked_at: now(),
    }])),
  }));
  if (replaceId == null) s.rag.recipes.push(...added);
  else s.rag.recipes = s.rag.recipes.map((r) => r.recipe_id === replaceId ? added[0] : r);
  event(s, u, type, rid);
  Object.assign(s.events[s.events.length - 1], { count: added.length, corpus_version: version });
  if (replaceId != null) s.events[s.events.length - 1].recipe_id = replaceId;
  return { added: added.length, recipe_id: added[0].recipe_id, corpus_version: version };
}
function currentRagRecord(s: MockState, req: Request, b: Record<string, unknown>) {
  const id = Number(resource(req, "/admin/rag/recipes/"));
  const record = s.rag.recipes.find((r) => r.recipe_id === id);
  if (!record) return fail(404, "NOT_FOUND", "Рецепт удалён или не найден. Обновите список.");
  if (typeof b.expected_version !== "string" || !b.expected_version.trim())
    return fail(400, "VALIDATION_ERROR", "Передайте expected_version записи.");
  if (record.corpus_version !== b.expected_version)
    return fail(409, "VERSION_CONFLICT", "Запись уже изменена. Обновите список и откройте актуальную запись.");
  return record;
}
function importText(b: Record<string, unknown>) {
  if (typeof b.text !== "string") fail(400, "VALIDATION_ERROR", "Передайте текст JSONL в поле text.");
  return b.text as string;
}
export const handlers = [
  route("put", "/admin/rag/recipes/:id", async (req, c, rid) => {
    admin(await readState(), c);
    const b = await body(req);
    const parsed = ragRecipeSchema.safeParse(b);
    const result = await updateState((s) => {
      const u = admin(s, c);
      const record = currentRagRecord(s, req, b);
      if (!parsed.success) return fail(400, "VALIDATION_ERROR", parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "));
      if (s.rag.recipes.some((r) => r.recipe_id !== record.recipe_id && recipeKey(r) === recipeKey(parsed.data)))
        return fail(409, "DUPLICATE_RECIPE", "Такой рецепт уже существует.");
      return addRagRecords(s, [parsed.data], u, rid, "rag_update", record.recipe_id);
    });
    return json(result, rid);
  }),
  route("delete", "/admin/rag/recipes/:id", async (req, c, rid) => {
    admin(await readState(), c);
    const b = await body(req);
    const result = await updateState((s) => {
      const u = admin(s, c);
      const record = currentRagRecord(s, req, b);
      s.rag.recipes = s.rag.recipes.filter((r) => r.recipe_id !== record.recipe_id);
      s.rag.revision++;
      const version = corpusVersion(s);
      event(s, u, "rag_delete", rid);
      Object.assign(s.events[s.events.length - 1], { recipe_id: record.recipe_id, count: 1, corpus_version: version });
      return { recipe_id: record.recipe_id, corpus_version: version };
    });
    return json(result, rid);
  }),
  route("get", "/admin/rag", async (req, c, rid) => {
    const s = await readState();
    admin(s, c);
    const params = new URL(req.url).searchParams;
    const limit = Math.max(1, Math.min(100, Math.trunc(Number(params.get("limit"))) || 50));
    const offset = Math.max(0, Math.trunc(Number(params.get("offset"))) || 0);
    return json({ items: s.rag.recipes.slice(offset, offset + limit), total: s.rag.recipes.length, corpus_version: corpusVersion(s) }, rid);
  }),
  route("post", "/admin/rag/recipes", async (req, c, rid) => {
    admin(await readState(), c);
    const parsed = ragRecipeSchema.safeParse(await body(req));
    if (!parsed.success) fail(400, "VALIDATION_ERROR", parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "));
    const result = await updateState((s) => {
      const u = admin(s, c);
      const record = parsed.data!;
      if (s.rag.recipes.some((r) => recipeKey(r) === recipeKey(record))) fail(409, "DUPLICATE_RECIPE", "Такой рецепт уже существует.");
      return addRagRecords(s, [record], u, rid, "rag_add");
    });
    return json(result, rid, 201);
  }),
  route("post", "/admin/rag/import/validate", async (req, c, rid) => {
    const s = await readState();
    admin(s, c);
    const text = importText(await body(req));
    const { records: _, ...report } = validateJsonl(text, s.rag.recipes);
    return json(report, rid);
  }),
  route("post", "/admin/rag/import", async (req, c, rid) => {
    admin(await readState(), c);
    const text = importText(await body(req));
    const result = await updateState((s) => {
      const u = admin(s, c);
      const report = validateJsonl(text, s.rag.recipes);
      if (report.errors.length) fail(400, "VALIDATION_ERROR", report.errors.map((e) => `Строка ${e.line}: ${e.message}`).join("; "));
      if (report.duplicates.length) fail(409, "DUPLICATE_RECIPE", report.duplicates.map((e) => `Строка ${e.line}: ${e.message}`).join("; "));
      return addRagRecords(s, report.records, u, rid, "rag_import");
    });
    return json(result, rid, 201);
  }),
  route("get", "/auth/me", async (_r, c, rid) =>
    json(publicUser(user(await readState(), c)), rid),
  ),
  route("post", "/auth/login", async (req, _c, rid) => {
    const parsed = credentialsSchema.safeParse(await body(req));
    if (!parsed.success)
      fail(400, "VALIDATION_ERROR", parsed.error.issues[0].message);
    const value = parsed.data!;
    const s = await readState();
    const u = s.users.find((u) => u.email === value.email.toLowerCase());
    if (!u || (await digest(value.password, u.salt)) !== u.digest)
      fail(401, "INVALID_CREDENTIALS", "Неверный email или пароль.");
    const session = uid();
    await updateState((st) => {
      st.sessions[session] = u!.user_id;
      event(st, u!, "login", rid);
    });
    return json(publicUser(u!), rid, 200, {
      "set-cookie": "chef_session=" + session + "; Path=/; SameSite=Lax",
    });
  }),
  route("post", "/auth/register", async (req, _c, rid) => {
    const b = await body(req);
    if ("role" in b)
      fail(
        400,
        "VALIDATION_ERROR",
        "Самостоятельная регистрация создаёт только пользователя.",
      );
    const parsed = credentialsSchema.safeParse(b);
    if (!parsed.success)
      fail(400, "VALIDATION_ERROR", parsed.error.issues[0].message);
    const u = await makeUser(parsed.data!.email, parsed.data!.password, "user");
    await updateState((s) => {
      if (s.users.some((n) => n.email === u.email))
        fail(409, "EMAIL_EXISTS", "Этот email уже зарегистрирован.");
      s.users.push(u);
      event(s, u, "register", rid);
    });
    return json(publicUser(u), rid, 201);
  }),
  route("post", "/auth/logout", async (_r, c, rid) => {
    await updateState((s) => {
      const u = user(s, c);
      event(s, u, "logout", rid);
      delete s.sessions[c.chef_session!];
    });
    return new HttpResponse(null, {
      status: 204,
      headers: {
        "set-cookie": "chef_session=; Max-Age=0; Path=/; SameSite=Lax",
      },
    });
  }),
  route("get", "/chats", async (_r, c, rid) => {
    const s = await readState();
    const u = user(s, c);
    const all = s.chats
      .filter((n) => ownerOf(n) === u.user_id)
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    const url = new URL(_r.url);
    const limit = Math.max(
      1,
      Math.min(100, Number(url.searchParams.get("limit")) || 50),
    );
    const offset = Math.max(0, Number(url.searchParams.get("offset")) || 0);
    return json(
      {
        items: all
          .slice(offset, offset + limit)
          .map(({ chat_id, title, created_at, updated_at }) => ({
            chat_id,
            title,
            created_at,
            updated_at,
          })),
        total: all.length,
      },
      rid,
    );
  }),
  route("get", "/chats/:id", async (req, c, rid) => {
    const s = await readState();
    const chat = owned(s, c, (n) => n.chat_id === resource(req, "/chats/"));
    const { owner_id: _, candidates: _candidates, demo_fixtures: _demoFixtures, ...out } = chat as OwnedChat;
    return json(
      {
        ...out,
        resume_status:
          s.mode === "unavailable" ? "recipe_unavailable" : chat.resume_status,
      },
      rid,
    );
  }),
  route("delete", "/chats/:id", async (req, c, rid) => {
    await updateState((s) => {
      const chat = owned(s, c, (n) => n.chat_id === resource(req, "/chats/"));
      const u = user(s, c);
      s.chats = s.chats.filter((n) => n.chat_id !== chat.chat_id);
      event(s, u, "delete_chat", rid);
    });
    return new HttpResponse(null, { status: 204 });
  }),
  route("post", "/selections", async (req, c, rid) => {
    const b = await body(req);
    const text =
      typeof b.products_text === "string" ? b.products_text.trim() : "";
    if (!text || text.length > 2000 || !ingredientTerms(text).length)
      fail(400, "VALIDATION_ERROR", "Перечислите продукты (до 2000 символов).");
    const result = await updateState((s) => {
      const u = user(s, c);
      if (s.mode === "search-error") {
        event(s, u, "search", rid, [], null, false, "SEARCH_UNAVAILABLE");
        return null;
      }
      const chat = seedChat(uid()) as OwnedChat;
      chat.owner_id = u.user_id;
      chat.title = text;
      chat.products_text = text;
      chat.demo_fixtures = structuredClone(s.rag.recipes.filter((r) => r.recipe_id === 5 || r.recipe_id === 7));
      chat.candidates = candidates(text, s.rag.recipes).map((r) => ({ ...r, corpus_version: corpusVersion(s) }));
      chat.selection_id = uid();
      chat.messages = [
        { message_id: uid(), role: "user", text, created_at: now() },
        {
          message_id: uid(),
          role: "assistant",
          text: "Подобрала несколько идей. Посмотрите, что понадобится добавить.",
          created_at: now(),
        },
      ];
      chat.selection = {
        ...chat.selection,
        chat_id: chat.chat_id,
        selection_id: chat.selection_id,
        request_id: rid,
        corpus_version: corpusVersion(s),
      };
      chat.selection = selection(chat, source(s, chat));
      s.chats.push(chat);
      event(
        s,
        u,
        "search",
        rid,
        chat.selection.items.map((r) => r.recipe_id),
        null, false, null, chat.selection.corpus_version,
      );
      return chat.selection;
    });
    if (!result)
      fail(
        503,
        "SEARCH_UNAVAILABLE",
        "Поиск временно недоступен. Повторите запрос.",
      );
    return json(result!, rid, 201);
  }),
  route("post", "/selections/:id/filter", async (req, c, rid) => {
    const b = await body(req);
    const filters = b.filters;
    if (!filters || typeof filters !== "object" || Array.isArray(filters))
      fail(400, "VALIDATION_ERROR", "Передайте объект filters.");
    const parsed = filtersSchema.safeParse(filters);
    if (!parsed.success)
      fail(400, "VALIDATION_ERROR", "Некорректные поля фильтров.");
    const f = parsed.data! as Filters;
    const error = validateFilters(f);
    if (error) fail(400, "VALIDATION_ERROR", error);
    const result = await updateState((s) => {
      const chat = owned(
        s,
        c,
        (n) => n.selection_id === resource(req, "/selections/"),
      );
      chat.filters = f;
      chat.updated_at = now();
      chat.selection = selection(chat, source(s, chat));
      chat.selection.request_id = rid;
      event(
        s,
        user(s, c),
        "filter",
        rid,
        chat.selection.items.map((r) => r.recipe_id),
        null, false, null, chat.selection.corpus_version,
      );
      return chat.selection;
    });
    return json(result, rid);
  }),
  route("post", "/selections/:id/recipe", async (req, c, rid) => {
    const b = await body(req);
    const result = await updateState((s) => {
      const chat = owned(
        s,
        c,
        (n) => n.selection_id === resource(req, "/selections/"),
      );
      const recipe = source(s, chat).find((r) => r.recipe_id === b.recipe_id);
      if (!recipe) fail(404, "NOT_FOUND", "Рецепт не найден в этом подборе.");
      const full = recipe as SelectedRecipe;
      if (!full.steps.length)
        fail(
          409,
          "RECIPE_INCOMPLETE",
          "В источнике нет проверенных шагов приготовления.",
          full.url,
        );
      chat.selected_recipe = {
        ...structuredClone(full),
        missing_ingredients: recipe!.missing_ingredients,
      };
      chat.conversation_id = uid();
      chat.resume_status =
        s.mode === "unavailable" ? "recipe_unavailable" : "ready";
      chat.updated_at = now();
      chat.messages.push({
        message_id: uid(),
        role: "assistant",
        text:
          "Выбран рецепт «" +
          full.title +
          "». Можно задавать вопросы по его шагам.",
        created_at: now(),
        recipe_id: full.recipe_id,
        conversation_id: chat.conversation_id,
      });
      event(s, user(s, c), "select_recipe", rid, [], full.recipe_id, false, null, chat.selection.corpus_version);
      return {
        ...chat.selected_recipe,
        chat_id: chat.chat_id,
        conversation_id: chat.conversation_id,
      };
    });
    return json(result, rid);
  }),
  route("post", "/conversations/:id/messages", async (req, c, rid) => {
    const b = await body(req);
    if (
      typeof b.text !== "string" ||
      !b.text.trim() ||
      typeof b.message_id !== "string" ||
      !b.message_id
    )
      fail(400, "VALIDATION_ERROR", "Укажите вопрос и message_id.");
    await delay(200);
    const out = await updateState((s) => {
      const chat = owned(
        s,
        c,
        (n) => n.conversation_id === resource(req, "/conversations/"),
      );
      const u = user(s, c);
      if (
        s.mode === "unavailable" ||
        chat.resume_status === "recipe_unavailable"
      )
        fail(
          409,
          "RECIPE_UNAVAILABLE",
          "Сохранённый рецепт доступен только для чтения. Начните новый подбор.",
        );
      if (s.mode === "llm-error") {
        event(
          s,
          u,
          "question",
          rid,
          [],
          chat.selected_recipe?.recipe_id || null,
          true,
          "LLM_UNAVAILABLE",
          chat.selection.corpus_version,
        );
        return null;
      }
      const existing = chat.messages.find(
        (m) => m.message_id === b.message_id + "-answer",
      );
      if (existing)
        return {
          chat_id: chat.chat_id,
          message_id: b.message_id,
          answer: existing.text,
          sources: existing.sources || [],
          status: existing.sources?.length
            ? ("answered" as const)
            : ("insufficient_context" as const),
        };
      const recipe = chat.selected_recipe!;
      const q = (b.text as string).toLowerCase();
      const insufficient =
        /температур|замен|калори|сколько градусов|друг.{0,5}блюд/.test(q);
      const answer = insufficient
        ? "В сохранённом рецепте нет этих сведений. Я не буду придумывать параметры или замену ингредиентов."
        : recipe.steps[1] || recipe.steps[0];
      const sources = insufficient
        ? []
        : [
            {
              recipe_id: recipe.recipe_id,
              url: recipe.url,
              step_numbers: [recipe.steps[1] ? 2 : 1],
            },
          ];
      chat.messages.push(
        {
          message_id: b.message_id as string,
          role: "user",
          text: (b.text as string).trim(),
          created_at: now(),
          conversation_id: chat.conversation_id!,
          recipe_id: recipe.recipe_id,
        },
        {
          message_id: b.message_id + "-answer",
          role: "assistant",
          text: answer,
          created_at: now(),
          conversation_id: chat.conversation_id!,
          recipe_id: recipe.recipe_id,
          sources,
        },
      );
      chat.updated_at = now();
      event(s, u, "question", rid, [], recipe.recipe_id, true, null, chat.selection.corpus_version);
      return {
        chat_id: chat.chat_id,
        message_id: b.message_id,
        answer,
        sources,
        status: insufficient
          ? ("insufficient_context" as const)
          : ("answered" as const),
      };
    });
    if (!out)
      fail(
        503,
        "LLM_UNAVAILABLE",
        "Помощник временно недоступен. Рецепт остаётся доступен.",
      );
    return json(out!, rid);
  }),
  route("get", "/admin/users", async (req, c, rid) => {
    const s = await readState();
    admin(s, c);
    const url = new URL(req.url);
    const limit = Math.min(
      100,
      Math.max(1, Number(url.searchParams.get("limit")) || 50),
    );
    const offset = Math.max(0, Number(url.searchParams.get("offset")) || 0);
    return json(
      {
        items: s.users.slice(offset, offset + limit).map(publicUser),
        total: s.users.length,
      },
      rid,
    );
  }),
  route("post", "/admin/users", async (req, c, rid) => {
    const s = await readState();
    admin(s, c);
    const parsed = userSchema.safeParse(await body(req));
    if (!parsed.success)
      fail(400, "VALIDATION_ERROR", parsed.error.issues[0].message);
    const { email, password, role } = parsed.data!;
    const made = await makeUser(email, password, role as Role);
    await updateState((st) => {
      const a = admin(st, c);
      if (st.users.some((u) => u.email === made.email))
        fail(409, "EMAIL_EXISTS", "Этот email уже зарегистрирован.");
      st.users.push(made);
      event(st, a, "create_user", rid);
      const ev = st.events[st.events.length - 1];
      ev.target_user_id = made.user_id;
      ev.assigned_role = made.role;
    });
    return json(publicUser(made), rid, 201);
  }),
  route("get", "/admin/activity", async (req, c, rid) => {
    const s = await readState();
    admin(s, c);
    const p = new URL(req.url).searchParams;
    const from = p.get("from")
      ? new Date(p.get("from")!).getTime()
      : Date.now() - 30 * 86400000;
    const to = p.get("to")
      ? new Date(p.get("to")!).getTime() + 86400000
      : Date.now();
    if (!Number.isFinite(from) || !Number.isFinite(to) || from > to)
      fail(400, "VALIDATION_ERROR", "Проверьте период.");
    const all = s.events
      .filter(
        (e) =>
          new Date(e.occurred_at).getTime() >= from &&
          new Date(e.occurred_at).getTime() <= to &&
          (!p.get("user_id") || e.user_id === p.get("user_id")),
      )
      .reverse();
    const limit = Math.min(100, Math.max(1, Number(p.get("limit")) || 50));
    const offset = Math.max(0, Number(p.get("offset")) || 0);
    return json(
      { items: all.slice(offset, offset + limit), total: all.length },
      rid,
    );
  }),
  route("get", "/admin/requests/:id", async (req, c, rid) => {
    const s = await readState();
    admin(s, c);
    const d = s.diagnostics[resource(req, "/admin/requests/")];
    if (!d) fail(404, "NOT_FOUND", "Диагностика не найдена.");
    return json(d!, rid);
  }),
  http.all(API_BASE + "/*", () =>
    HttpResponse.json(
      {
        error: {
          code: "MOCK_NOT_IMPLEMENTED",
          message: "Этот API-маршрут не реализован в моках.",
        },
        request_id: uid(),
      },
      { status: 501 },
    ),
  ),
];
