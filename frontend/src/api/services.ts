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
