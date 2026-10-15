"""Подготовка корпуса рецептов.

Основной источник (с 15.10.2026): датасет d0rj/povarenok_recipes_detail (HuggingFace, Apache-2.0),
подробная выгрузка povarenok.ru: описание, ингредиенты с количествами, время, порции, шаги,
категории, КБЖУ. Parquet-файлы сначала переводятся в JSONL: `python -m rag.convert_parquet`.

Старый источник (только название + ингредиенты) — rogozinushka/povarenok-recipes (CSV) —
по-прежнему поддерживается.

Запуск:
    python -m rag.corpus data/raw/povarenok_detail.jsonl          # новый корпус
    python -m rag.corpus data/raw/povarenok_recipes_2021_06_16.csv # старый корпус
Результат:
    data/corpus.jsonl        карточки рецептов (без шагов) — то, что грузит поиск;
    data/steps.jsonl         шаги приготовления, строка N = рецепт с id N;
    data/steps_offsets.json  смещения строк steps.jsonl для чтения шагов одного рецепта;
    data/corpus_meta.json    версия корпуса, источник, статистика, правила очистки.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFAULT_OUT = DATA / "corpus.jsonl"
STEPS_PATH = DATA / "steps.jsonl"
STEPS_OFFSETS = DATA / "steps_offsets.json"
META_PATH = DATA / "corpus_meta.json"

MIN_INGREDIENTS = 2
MAX_TIME_MINUTES = 30 * 24 * 60      # больше 30 суток — явная ошибка ввода на сайте
MAX_KCAL_100G = 900                  # больше, чем у чистого жира, — невозможно
SPACE_RE = re.compile(r"\s+")
TIME_RE = re.compile(r"^\s*(\d+)\s*мин", re.I)


def clean_text(s: str) -> str:
    return SPACE_RE.sub(" ", s.replace("\xa0", " ")).strip()


def clean_ingredient_name(name: str) -> str:
    """Чистит название ингредиента.

    «Яйцо куриное» -> «Яйцо»: прилагательное «куриное» иначе превращается
    в терм «курица» и рецепты с яйцами начинают находиться по запросу «курица».
    """
    name = clean_text(name)
    first = name.lower().split(" ", 1)[0]
    if first.startswith(("яйц", "яичн")) or first in {"желток", "желтки", "белок", "белки"}:
        name = re.sub(r"\s*куриные?|\s*куриное|\s*куриный", "", name, flags=re.I).strip()
    return name


def _clean_ingredients(pairs) -> list[dict]:
    out, seen = [], set()
    for name, amount in pairs:
        if not isinstance(name, str):
            continue
        name = clean_ingredient_name(name)
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "amount": clean_text(amount) if isinstance(amount, str) and amount.strip() else None})
    return out


def parse_ingredients(raw: str) -> list[dict]:
    """Ингредиенты старого CSV: словарь Python в виде строки."""
    if not raw or raw.strip() in {"", "None", "nan"}:
        return []
    try:
        data = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(data, dict):
        return []
    return _clean_ingredients(data.items())


def parse_time(raw) -> int | None:
    """«40 минут» -> 40. Пусто, 0 или больше 30 суток -> None (нет данных)."""
    if not isinstance(raw, str):
        return None
    m = TIME_RE.match(raw)
    if not m:
        return None
    v = int(m.group(1))
    return v if 0 < v <= MAX_TIME_MINUTES else None


def parse_int(raw) -> int | None:
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def parse_nutrition(nae) -> dict:
    """КБЖУ на 100 г блюда из поля nae_value (рассчитаны калькулятором povarenok.ru).

    Все нули — калькулятор сайта не посчитал: None. Значения, невозможные физически
    (больше 900 ккал или больше 100 г нутриента на 100 г), — тоже None.
    """
    empty = {"kcal": None, "protein_g": None, "fat_g": None, "carbs_g": None}
    h = (nae or {}).get("100 г блюда") if isinstance(nae, dict) else None
    if not isinstance(h, dict):
        return empty
    vals = {"kcal": h.get("kcal"), "protein_g": h.get("protein"), "fat_g": h.get("fats"), "carbs_g": h.get("carb")}
    if any(not isinstance(v, (int, float)) for v in vals.values()):
        return empty
    if all(v == 0 for v in vals.values()):
        return empty
    if vals["kcal"] < 0 or vals["kcal"] > MAX_KCAL_100G or any(
            v < 0 or v > 100 for k, v in vals.items() if k != "kcal"):
        return empty
    return {k: round(float(v), 1) for k, v in vals.items()}


def doc_text(recipe: dict) -> str:
    """Текст документа для индекса: название + категории + названия ингредиентов.

    Категории сайта («Супы», «Салаты», «Выпечка») помогают запросам с типом блюда.
    Количества, описание и шаги не индексируются: поиск идёт по продуктам и типу блюда.
    """
    return " ".join([recipe["title"], *recipe.get("categories", []),
                     *(i["name"] for i in recipe["ingredients"])])


# --------------------------------------------------------------------------- подробный корпус
def prepare_detail(raw_path: Path, out_path: Path = DEFAULT_OUT) -> dict:
    stats = Counter()
    seen = set()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    offsets: list[int] = []
    n = 0
    with open(raw_path, encoding="utf-8") as src, \
            open(out_path, "w", encoding="utf-8") as out, \
            open(STEPS_PATH, "wb") as steps_out:
        for line in src:
            if not line.strip():
                continue
            row = json.loads(line)
            stats["raw"] += 1
            title = clean_text(row.get("title") or "")
            ingredients = _clean_ingredients(
                (i.get("name"), i.get("count")) for i in (row.get("ingredients") or []) if isinstance(i, dict))
            if not title:
                stats["skip_no_title"] += 1
                continue
            if len(ingredients) < MIN_INGREDIENTS:
                stats["skip_few_ingredients"] += 1
                continue
            key = (title.lower(), frozenset(i["name"].lower() for i in ingredients))
            if key in seen:
                stats["skip_duplicate"] += 1
                continue
            seen.add(key)

            nutrition = parse_nutrition(row.get("nae_value"))
            time_min = parse_time(row.get("cooking_time"))
            steps = [clean_text(s) for s in (row.get("cooking_steps") or []) if isinstance(s, str) and s.strip()]
            description = clean_text(row.get("description") or "") or None
            recipe = {
                "id": n,
                "title": title,
                "description": description,
                "ingredients": ingredients,
                "url": (row.get("page_url") or "").strip(),
                "source": "povarenok.ru",
                "categories": [clean_text(c) for c in (row.get("kroshki") or []) if isinstance(c, str)],
                "tags": [clean_text(t) for t in (row.get("tags") or []) if isinstance(t, str)],
                "total_time_minutes": time_min,
                "portions": parse_int(row.get("portions_count")),
                "nutrition_per_100g": nutrition,
                "has_steps": bool(steps),
            }
            out.write(json.dumps(recipe, ensure_ascii=False) + "\n")
            offsets.append(steps_out.tell())
            steps_out.write((json.dumps({"id": n, "steps": steps}, ensure_ascii=False) + "\n").encode("utf-8"))

            stats["with_time"] += time_min is not None
            stats["with_nutrition"] += nutrition["kcal"] is not None
            stats["with_steps"] += bool(steps)
            stats["with_description"] += description is not None
            if row.get("cooking_time") and time_min is None:
                stats["time_rejected"] += 1
            n += 1
    STEPS_OFFSETS.write_text(json.dumps(offsets), encoding="utf-8")
    stats["kept"] = n
    meta = {
        "corpus_version": f"povarenok-detail-{n}-{datetime.now(timezone.utc):%Y%m%d}",
        "source_dataset": "https://huggingface.co/datasets/d0rj/povarenok_recipes_detail",
        "source_site": "povarenok.ru",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "records": n,
        "stats": dict(stats),
        "rules": {
            "min_ingredients": MIN_INGREDIENTS,
            "duplicates": "одинаковые название (без регистра) и множество ингредиентов",
            "time": f"поле cooking_time в минутах; 0 или больше {MAX_TIME_MINUTES} мин -> null",
            "nutrition": "nae_value['100 г блюда'] — расчёт калькулятора povarenok.ru по составу; "
                         f"все нули или больше {MAX_KCAL_100G} ккал / 100 г нутриента -> null",
        },
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(stats)


# --------------------------------------------------------------------------- старый корпус (CSV)
def load_raw(path: Path):
    csv.field_size_limit(10_000_000)
    with open(path, encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def prepare(raw_path: Path, out_path: Path = DEFAULT_OUT) -> dict:
    stats = Counter()
    seen = set()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for row in load_raw(raw_path):
            stats["raw"] += 1
            title = clean_text(row.get("name") or "")
            ingredients = parse_ingredients(row.get("ingredients") or "")
            if not title:
                stats["skip_no_title"] += 1
                continue
            if len(ingredients) < MIN_INGREDIENTS:
                stats["skip_few_ingredients"] += 1
                continue
            key = (title.lower(), frozenset(i["name"].lower() for i in ingredients))
            if key in seen:
                stats["skip_duplicate"] += 1
                continue
            seen.add(key)
            recipe = {"id": n, "title": title, "ingredients": ingredients,
                      "url": (row.get("url") or "").strip(), "source": "povarenok.ru"}
            out.write(json.dumps(recipe, ensure_ascii=False) + "\n")
            n += 1
    stats["kept"] = n
    return dict(stats)


# --------------------------------------------------------------------------- чтение
def load_corpus(path: Path = DEFAULT_OUT) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_meta() -> dict:
    return json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}


class StepsStore:
    """Шаги одного рецепта по id без загрузки всего файла в память."""

    def __init__(self, steps_path: Path = STEPS_PATH, offsets_path: Path = STEPS_OFFSETS):
        self.path = steps_path
        self.offsets = json.loads(offsets_path.read_text(encoding="utf-8")) if offsets_path.exists() else []

    def get(self, recipe_id: int) -> list[str]:
        if not (0 <= recipe_id < len(self.offsets)):
            return []
        with open(self.path, "rb") as f:
            f.seek(self.offsets[recipe_id])
            row = json.loads(f.readline().decode("utf-8"))
        return row["steps"] if row.get("id") == recipe_id else []


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Подготовка корпуса рецептов")
    ap.add_argument("raw", type=Path, help="data/raw/povarenok_detail.jsonl или старый CSV")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    fn = prepare if args.raw.suffix.lower() == ".csv" else prepare_detail
    stats = fn(args.raw, args.out)
    json.dump(stats, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
