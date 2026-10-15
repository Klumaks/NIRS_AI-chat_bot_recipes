export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId?: string,
    public sourceUrl?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "/api/v1"
).replace(/\/$/, "");
export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(API_BASE + path, {
      ...init,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(
      0,
      "NETWORK_ERROR",
      "Сервис недоступен. Проверьте подключение и повторите запрос.",
    );
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json"))
    throw new ApiError(
      response.status,
      "INVALID_RESPONSE",
      "API недоступен или вернул неожиданный ответ.",
    );
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(
      response.status,
      data.error?.code || "UNKNOWN_ERROR",
      data.error?.message || "Не удалось выполнить запрос.",
      data.request_id,
      data.error?.source_url,
    );
  return data as T;
}
export const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });
