"""Ошибки API в формате контракта: {"request_id": "…", "error": {"code": "…", "message": "…"}}."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, source_url: str | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.source_url = source_url
        self.headers = headers or {}


def validation(message: str) -> ApiError:
    return ApiError(400, "VALIDATION_ERROR", message)


def auth_required() -> ApiError:
    return ApiError(401, "AUTH_REQUIRED", "Войдите в аккаунт, чтобы продолжить.")


def forbidden() -> ApiError:
    return ApiError(403, "FORBIDDEN", "Этот раздел доступен только администратору.")


def not_found(message: str = "Чат не найден или недоступен.") -> ApiError:
    return ApiError(404, "NOT_FOUND", message)


def search_unavailable() -> ApiError:
    return ApiError(503, "SEARCH_UNAVAILABLE", "Поиск временно недоступен. Повторите запрос.")


def llm_unavailable() -> ApiError:
    return ApiError(503, "LLM_UNAVAILABLE", "Помощник временно недоступен. Рецепт остаётся доступен.")
