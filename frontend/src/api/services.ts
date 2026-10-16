import type { RagRecipeInput } from "../lib/rag";
import { post, request } from "./client";
import type {
  User,
  Role,
  Chat,
  ChatSummary,
  Selection,
  Filters,
  RecipeResponse,
  Answer,
  List,
  Activity,
  Diagnostic,
  RagList,
  RagValidation,
  RagWrite,
} from "./types";
export const authApi = {
  me: (signal?: AbortSignal) => request<User>("/auth/me", { signal }),
  login: (email: string, password: string) =>
    post<User>("/auth/login", { email, password }),
  register: (email: string, password: string) =>
    post<User>("/auth/register", { email, password }),
  logout: () => post<void>("/auth/logout", {}),
};
export const chatApi = {
  list: (signal?: AbortSignal) =>
    request<List<ChatSummary>>("/chats", { signal }),
  detail: (id: string, signal?: AbortSignal) =>
    request<Chat>("/chats/" + encodeURIComponent(id), { signal }),
  create: (products_text: string) =>
    post<Selection>("/selections", { products_text }),
  filter: (id: string, filters: Filters) =>
    post<Selection>("/selections/" + encodeURIComponent(id) + "/filter", {
      filters,
    }),
  select: (id: string, recipe_id: number) =>
    post<RecipeResponse>("/selections/" + encodeURIComponent(id) + "/recipe", {
      recipe_id,
    }),
  remove: (id: string) =>
    request<void>("/chats/" + encodeURIComponent(id), { method: "DELETE" }),
  message: (id: string, message_id: string, text: string) =>
    post<Answer>("/conversations/" + encodeURIComponent(id) + "/messages", {
      message_id,
      text,
    }),
};
export const adminApi = {
  rag: (offset = 0, signal?: AbortSignal) => request<RagList>(`/admin/rag?limit=20&offset=${offset}`, { signal }),
  addRecipe: (recipe: RagRecipeInput) => post<RagWrite>("/admin/rag/recipes", recipe),
  updateRecipe: (id: number, recipe: RagRecipeInput, expected_version: string) =>
    request<RagWrite>(`/admin/rag/recipes/${id}`, { method: "PUT", body: JSON.stringify({ ...recipe, expected_version }) }),
  deleteRecipe: (id: number, expected_version: string) =>
    request<RagWrite>(`/admin/rag/recipes/${id}`, { method: "DELETE", body: JSON.stringify({ expected_version }) }),
  validateImport: (text: string) => post<RagValidation>("/admin/rag/import/validate", { text }),
  importRecipes: (text: string) => post<RagWrite>("/admin/rag/import", { text }),
  users: (signal?: AbortSignal) =>
    request<List<User>>("/admin/users?limit=100", { signal }),
  create: (email: string, password: string, role: Role) =>
    post<User>("/admin/users", { email, password, role }),
  activity: (params: URLSearchParams, signal?: AbortSignal) =>
    request<List<Activity>>("/admin/activity?" + params.toString(), { signal }),
  diagnostic: (id: string, signal?: AbortSignal) =>
    request<Diagnostic>("/admin/requests/" + encodeURIComponent(id), {
      signal,
    }),
};
