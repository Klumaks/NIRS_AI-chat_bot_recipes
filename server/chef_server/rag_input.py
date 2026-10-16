"""Проверка рецептов из админки и JSONL (ADM-04, SC-13).

Правила — из контракта Максима (spec/tech/contracts.md, frontend/src/lib/rag.ts): название,
минимум два ингредиента, HTTP/HTTPS-источник обязательны; описание, шаги, КБЖУ на 100 г
(конечные неотрицательные числа) и время (положительное целое) — нет; неизвестное — null/[];
строки обрезаются по краям. Правила качества данных корпуса сервер не добавляет (это зона
корпуса). Сверх контракта — только ограничения размеров полей для защиты сервера.
"""
from __future__ import annotations

import json
import math
import re
from urllib.parse import urlparse

MAX_JSONL_BYTES = 5 * 1024 * 1024
MAX_JSONL_RECORDS = 1000
NUTRITION_KEYS = ("kcal", "protein_g", "fat_g", "carbs_g")
LIMITS = {"title": 300, "name": 200, "amount": 100, "description": 4000, "step": 4000, "url": 2000,
          "ingredients": 100, "steps": 100}
EMPTY = "Поле не должно быть пустым"
_SPACE = re.compile(r"\s+")


def _clean(s: str) -> str:
    return s.strip()


class _Errors(list):
    def add(self, path: str, message: str) -> None:
        self.append(f"{path}: {message}" if path else message)


def _text(value, path: str, errors: _Errors, limit: int, required: bool):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        errors.add(path, "Ожидается строка" if value is not None else "Обязательное поле")
        return None
    value = _clean(value)
    if not value:
        errors.add(path, EMPTY)
        return None
    if len(value) > limit:
        errors.add(path, f"Не более {limit} символов")
        return None
    return value


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_recipe(obj) -> tuple[dict | None, list[str]]:
    """Возвращает (нормализованный рецепт без id, []) или (None, [ошибки «поле: сообщение»])."""
    errors = _Errors()
    if not isinstance(obj, dict):
        return None, ["Ожидается JSON-объект рецепта"]
    title = _text(obj.get("title"), "title", errors, LIMITS["title"], True)

    url = obj.get("url")
    if not isinstance(url, str) or not url.strip():
        errors.add("url", "Нужна ссылка на источник")
        url = None
    else:
        url = url.strip()
        parsed = urlparse(url)
        if len(url) > LIMITS["url"]:
            errors.add("url", f"Не более {LIMITS['url']} символов")
        elif parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            errors.add("url", "Источник должен использовать HTTP/HTTPS")

    ingredients = []
    raw_ings = obj.get("ingredients")
    if not isinstance(raw_ings, list):
        errors.add("ingredients", "Нужно минимум два ингредиента")
    else:
        if len(raw_ings) < 2:
            errors.add("ingredients", "Нужно минимум два ингредиента")
        if len(raw_ings) > LIMITS["ingredients"]:
            errors.add("ingredients", f"Не более {LIMITS['ingredients']} ингредиентов")
        for i, ing in enumerate(raw_ings[: LIMITS["ingredients"]]):
            if not isinstance(ing, dict):
                errors.add(f"ingredients.{i}", "Ожидается объект с name и amount")
                continue
            name = _text(ing.get("name"), f"ingredients.{i}.name", errors, LIMITS["name"], True)
            amount = _text(ing.get("amount"), f"ingredients.{i}.amount", errors, LIMITS["amount"], False)
            if name:
                ingredients.append({"name": name, "amount": amount})

    description = _text(obj.get("description"), "description", errors, LIMITS["description"], False)

    steps = []
    raw_steps = obj.get("steps")
    if raw_steps is not None:
        if not isinstance(raw_steps, list):
            errors.add("steps", "Ожидается список строк")
        else:
            if len(raw_steps) > LIMITS["steps"]:
                errors.add("steps", f"Не более {LIMITS['steps']} шагов")
            for i, step in enumerate(raw_steps[: LIMITS["steps"]]):
                s = _text(step, f"steps.{i}", errors, LIMITS["step"], True)
                if s:
                    steps.append(s)

    nutrition = {k: None for k in NUTRITION_KEYS}
    raw_n = obj.get("nutrition_per_100g")
    if raw_n is not None:
        if not isinstance(raw_n, dict):
            errors.add("nutrition_per_100g", "Ожидается объект")
        else:
            for key in NUTRITION_KEYS:
                v = raw_n.get(key)
                if v is None:
                    continue
                if not _number(v) or v < 0:
                    errors.add(f"nutrition_per_100g.{key}", "Нужно конечное неотрицательное число или null")
                else:
                    nutrition[key] = float(v) if isinstance(v, float) else v

    time_ = obj.get("total_time_minutes")
    if time_ is not None:
        if not _number(time_) or time_ != int(time_) or time_ <= 0:
            errors.add("total_time_minutes", "Нужно положительное целое число минут или null")
            time_ = None
        else:
            time_ = int(time_)

    if "id" in obj and obj["id"] is not None and (not isinstance(obj["id"], int) or isinstance(obj["id"], bool)):
        errors.add("id", "Ожидается целое число")
    if "source" in obj and obj["source"] is not None and not isinstance(obj["source"], str):
        errors.add("source", "Ожидается строка")

    if errors:
        return None, list(errors)
    return {
        "title": title, "description": description, "ingredients": ingredients, "url": url,
        "source": "admin", "categories": [], "tags": [], "total_time_minutes": time_, "portions": None,
        "nutrition_per_100g": nutrition, "has_steps": bool(steps), "steps": steps,
    }, []


def canonical(s: str) -> str:
    return _SPACE.sub(" ", s.strip().lower().replace("ё", "е"))


def recipe_key(record: dict) -> str:
    """Дубликат: одинаковые название без регистра и множество названий ингредиентов
    (то же правило, что при очистке корпуса и в lib/rag.ts)."""
    names = sorted({canonical(i["name"]) for i in record["ingredients"]})
    return json.dumps([canonical(record["title"]), names], ensure_ascii=False)


def parse_jsonl(text: str) -> tuple[list[tuple[int, dict]], list[dict], int]:
    """Разбор JSONL: (корректные записи с номерами строк, ошибки {line, message}, число записей).
    Номера строк начинаются с 1, пустые строки пропускаются, BOM удаляется."""
    errors: list[dict] = []
    records: list[tuple[int, dict]] = []
    if len(text.encode("utf-8")) > MAX_JSONL_BYTES:
        return [], [{"line": 1, "message": "Файл превышает 5 МиБ"}], 0
    count = 0
    for index, raw in enumerate(text.lstrip("﻿").splitlines()):
        if not raw.strip():
            continue
        count += 1
        line = index + 1
        if count > MAX_JSONL_RECORDS:
            errors.append({"line": line, "message": "Не более 1000 записей"})
            break
        try:
            obj = json.loads(raw)
        except ValueError:
            errors.append({"line": line, "message": "Некорректный JSON"})
            continue
        record, problems = parse_recipe(obj)
        if problems:
            errors.append({"line": line, "message": "; ".join(problems)})
        else:
            records.append((line, record))
    if not count:
        errors.append({"line": 1, "message": "Файл не содержит записей"})
    return records, errors, min(count, MAX_JSONL_RECORDS + 1)
