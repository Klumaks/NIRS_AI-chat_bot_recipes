import { openDB } from "idb";
import type { User, Chat, Activity, Diagnostic, SelectedRecipe } from "../api/types";
import { candidates, recipes } from "./fixtures";
export interface StoredUser extends User {
  salt: string;
  digest: string;
}
export interface MockState {
  users: StoredUser[];
  sessions: Record<string, string>;
  chats: Chat[];
  events: Activity[];
  diagnostics: Record<string, Diagnostic>;
  mode: DemoMode;
  rag: { recipes: SelectedRecipe[]; revision: number; next_id: number };
}
export const corpusVersion = (s: MockState) => `demo-corpus-v${s.rag.revision}`;

/** Upgrade the kv payload without replacing accounts, conversations or recipe snapshots. */
function migrateState(s: MockState): MockState {
  s.rag ??= { recipes: structuredClone(recipes), revision: 1, next_id: 8 };
  for (const c of s.chats as OwnedChat[]) {
    c.candidates ??= candidates(c.products_text);
    c.demo_fixtures ??= structuredClone(recipes.filter((r) => r.recipe_id === 5 || r.recipe_id === 7));
  }
  if (s.rag.next_id == null) {
    let highest = s.rag.recipes.reduce((max, r) => Math.max(max, r.recipe_id), 0);
    for (const c of s.chats as OwnedChat[]) {
      for (const r of [...(c.candidates ?? []), ...(c.demo_fixtures ?? []), ...c.selection.items]) highest = Math.max(highest, r.recipe_id);
      if (c.selected_recipe) highest = Math.max(highest, c.selected_recipe.recipe_id);
    }
    s.rag.next_id = highest + 1;
  }
  // Legacy snapshots may still contain this removed API field, including provenance.
  function removeDifficulty(value: unknown) {
    if (!value || typeof value !== "object") return;
    const object = value as Record<string, unknown>;
    delete object.difficulty;
    Object.values(object).forEach(removeDifficulty);
  }
  removeDifficulty(s);
  return s;
}
export type DemoMode =
  | "normal"
  | "empty"
  | "unknown"
  | "incomplete"
  | "unavailable"
  | "search-error"
  | "llm-error"
  | "expired";
export interface DemoAccess {
  email: string;
  password: string;
  role: "user" | "admin";
}
const dbPromise = () =>
  openDB("ai-chef-demo", 1, {
    upgrade(db) {
      db.createObjectStore("kv");
    },
  });
export const now = () => new Date().toISOString();
export const uid = () => crypto.randomUUID();
export async function digest(password: string, salt: string) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const b = await crypto.subtle.deriveBits(
    {
      name: "PBKDF2",
      salt: new TextEncoder().encode(salt),
      iterations: 100_000,
      hash: "SHA-256",
    },
    key,
    256,
  );
  return [...new Uint8Array(b)]
    .map((v) => v.toString(16).padStart(2, "0"))
    .join("");
}
export async function makeUser(
  email: string,
  password: string,
  role: "user" | "admin",
  id: string = uid(),
): Promise<StoredUser> {
  const salt = uid();
  return {
    user_id: id,
    email: email.trim().toLowerCase(),
    role,
    created_at: now(),
    salt,
    digest: await digest(password, salt),
  };
}
export const publicUser = ({
  user_id,
  email,
  role,
  created_at,
}: StoredUser): User => ({ user_id, email, role, created_at });
export function seedChat(id: string): Chat {
  const time = now();
  const all = candidates("Курица, рис и лук");
  return {
    chat_id: id,
    title: "Курица, рис и лук",
    created_at: time,
    updated_at: time,
    messages: [
      {
        message_id: uid(),
        role: "user",
        text: "Курица, рис и лук",
        created_at: time,
      },
      {
        message_id: uid(),
        role: "assistant",
        text: "Вот несколько идей для вашего ужина. Все рецепты в этом режиме — демонстрационные.",
        created_at: time,
      },
    ],
    selection_id: "selection-" + id,
    products_text: "Курица, рис и лук",
    filters: {},
    selected_recipe: null,
    conversation_id: null,
    resume_status: "ready",
    selection: {
      chat_id: id,
      selection_id: "selection-" + id,
      corpus_version: "demo-corpus-v1",
      filters: {},
      items: all.slice(0, 5),
      total: all.length,
      request_id: "demo-request-1",
    },
  };
}
export async function readState(): Promise<MockState> {
  const db = await dbPromise();
  const s = await db.get("kv", "state");
  if (!s) throw new Error("Demo store not initialized");
  return migrateState(s);
}
export async function updateState<T>(fn: (s: MockState) => T): Promise<T> {
  const db = await dbPromise();
  const tx = db.transaction("kv", "readwrite");
  const s: MockState = await tx.store.get("state");
  if (!s) throw new Error("Demo store not initialized");
  migrateState(s);
  const result = fn(s);
  await tx.store.put(s, "state");
  await tx.done;
  return result;
}
export async function initializeDemo(reset = false): Promise<DemoAccess[]> {
  // Public credentials for local HTTP mocks only, documented in README.
  const access: DemoAccess[] = [
    {
      email: "user@ai-chef.test",
      role: "user",
      password: "DemoUser123!",
    },
    {
      email: "admin@ai-chef.test",
      role: "admin",
      password: "DemoAdmin123!",
    },
  ];
  const users = await Promise.all(
    access.map((a, i) =>
      makeUser(a.email, a.password, a.role, i ? "demo-admin" : "demo-user"),
    ),
  );
  const db = await dbPromise();
  const tx = db.transaction("kv", "readwrite");
  let state: MockState | undefined = reset
    ? undefined
    : await tx.store.get("state");
  if (!state) {
    const first = seedChat("demo-chat-1");
    const second = seedChat("demo-admin-chat");
    const other = seedChat("demo-other-chat");
    state = {
      users,
      sessions: {},
      chats: [first, second, other],
      events: [],
      diagnostics: {},
      mode: "normal",
      rag: { recipes: structuredClone(recipes), revision: 1, next_id: 8 },
    };
    // Ownership is private mock storage metadata, never a client-supplied field.
    state.chats.forEach((c, i) =>
      owners.set(
        c,
        i === 1 ? "demo-admin" : i === 2 ? "demo-other" : "demo-user",
      ),
    );
    for (const c of state.chats) (c as OwnedChat).owner_id = owners.get(c)!;
    state.diagnostics["demo-request-1"] = {
      request_id: "demo-request-1",
      corpus_version: "demo-corpus-v1",
      index_version: null,
      normalization_mode: "demo (не BM25)",
      candidate_ids: recipes.slice(0, 3).map((r) => r.recipe_id),
      selected_recipe_id: null,
      llm_called: false,
      model: null,
      error_code: null,
      stages: [
        { name: "Предобработка (демо)", status: "ok", duration_ms: 2 },
        { name: "Поиск по фикстурам", status: "ok", duration_ms: 8 },
        { name: "LLM", status: "not_run", duration_ms: null },
      ],
    };
    state.events = [
      {
        occurred_at: now(),
        user_id: "demo-user",
        event_type: "search",
        status: "ok",
        duration_ms: 10,
        request_id: "demo-request-1",
      },
    ];
  } else {
    state.users = state.users
      .filter((u) => !users.some((n) => n.user_id === u.user_id))
      .concat(users);
    state.mode = "normal";
  }
  migrateState(state);
  await tx.store.put(state, "state");
  await tx.done;
  return access;
}
const owners = new WeakMap<Chat, string>();
export type OwnedChat = Chat & { owner_id: string; candidates?: SelectedRecipe[]; demo_fixtures?: SelectedRecipe[] };
export function ownerOf(c: Chat) {
  return (c as OwnedChat).owner_id;
}
export async function setMode(mode: DemoMode) {
  await updateState((s) => {
    s.mode = mode;
    if (mode === "expired") s.sessions = {};
  });
}
export async function resetStore() {
  const db = await dbPromise();
  await db.clear("kv");
}
