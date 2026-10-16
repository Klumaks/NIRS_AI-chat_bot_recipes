"""Поиск рецептов по ингредиентам — публичный интерфейс модуля RAG.

Контракт для интеграции (см. spec/tech/rag.md, раздел «Интерфейс»):

    from rag.search import RecipeSearcher
    searcher = RecipeSearcher.load()                       # корпус + готовый индекс
    hits = searcher.search("курица, рис и лук", k=5)        # карточки рецептов
    page = searcher.select("курица, рис", k=5, filters={"kcal": {"max": 200},
                                                        "max_total_time_minutes": 40})
    # -> {"items": [...карточки...], "total": число рецептов после фильтров}
    full = searcher.get_recipe(123)                         # карточка + шаги приготовления

Сборка индекса:
    python -m rag.search build
Поиск из консоли:
    python -m rag.search query "что приготовить из фарша и картошки" -k 5
    python -m rag.search query "курица рис лук" --all      # все рецепты со всеми продуктами
    python -m rag.search query "курица рис" --kcal :150 --max-time 40
    python -m rag.search recipe 123                          # полный рецепт с шагами
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

from .bm25 import BM25Index
from .corpus import DEFAULT_OUT as CORPUS_PATH, StepsStore, doc_text, load_corpus, load_meta
from .text import get_normalizer

DATA = Path(__file__).resolve().parent.parent / "data"

# Базовые продукты, которые обычно есть дома. В «Не хватает» они не выводятся никогда.
PANTRY = {
    "соль", "вода", "перец черный", "перец черный молотый", "специи", "приправа",
    "масло растительное", "масло подсолнечное", "лед",
}
# Слова-уточнения, по которым одного совпадения мало: «перец черный» не должен
# считаться имеющимся, если пользователь написал «черный хлеб».
MODIFIERS = {
    "черный", "белый", "красный", "зеленый", "желтый", "сладкий", "свежий", "сухой",
    "твердый", "мягкий", "молотый", "репчатый", "пшеничный", "консервированный",
    "замороженный", "копченый", "соленый", "маринованный", "домашний", "столовый",
}
NUTRITION_KEYS = ("kcal", "protein_g", "fat_g", "carbs_g")
EMPTY_NUTRITION = {k: None for k in NUTRITION_KEYS}


def index_path(mode: str, corpus_path: Path = CORPUS_PATH) -> Path:
    """Индекс хранится рядом с корпусом: data/index_<корпус>_<режим>.pkl."""
    return DATA / f"index_{Path(corpus_path).stem}_{mode}.pkl"


def validate_filters(filters: dict | None) -> dict:
    """Проверка фильтров по правилам контракта (contracts.md): границы включаются,
    числа конечные и неотрицательные, min <= max, время — положительное целое."""
    filters = filters or {}
    for key in NUTRITION_KEYS:
        rng = filters.get(key) or {}
        lo, hi = rng.get("min"), rng.get("max")
        for v in (lo, hi):
            if v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0):
                raise ValueError(f"{key}: границы должны быть конечными неотрицательными числами")
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"{key}: минимум больше максимума")
    t = filters.get("max_total_time_minutes")
    if t is not None and (not isinstance(t, int) or t <= 0):
        raise ValueError("max_total_time_minutes: нужно положительное целое число минут")
    return filters


def matches_filters(recipe: dict, filters: dict) -> bool:
    """Неизвестное значение (null) исключает рецепт, если по этому полю есть ограничение."""
    n = recipe.get("nutrition_per_100g") or EMPTY_NUTRITION
    for key in NUTRITION_KEYS:
        rng = filters.get(key) or {}
        lo, hi = rng.get("min"), rng.get("max")
        if lo is None and hi is None:
            continue
        v = n.get(key)
        if v is None or (lo is not None and v < lo) or (hi is not None and v > hi):
            return False
    t = filters.get("max_total_time_minutes")
    if t is not None:
        v = recipe.get("total_time_minutes")
        if v is None or v > t:
            return False
    return True


class RecipeSearcher:
    def __init__(self, corpus: list[dict], index: BM25Index, mode: str):
        self.corpus = corpus
        self.index = index
        self.normalizer = get_normalizer(mode)
        self.mode = self.normalizer.mode
        self._modifiers = {self.normalizer.word(w) for w in MODIFIERS}
        self._by_id = {r["id"]: i for i, r in enumerate(corpus)}
        self._steps: StepsStore | None = None
        self.meta = load_meta()

    # ------------------------------------------------------------------
    @classmethod
    def build(cls, corpus: list[dict], mode: str = "lemma", k1: float = 1.5, b: float = 0.75):
        norm = get_normalizer(mode)
        index = BM25Index(k1=k1, b=b).build(norm.tokens(doc_text(r)) for r in corpus)
        return cls(corpus, index, norm.mode)

    @classmethod
    def load(cls, mode: str = "lemma", corpus_path: Path = CORPUS_PATH) -> "RecipeSearcher":
        mode = get_normalizer(mode).mode  # учитываем откат lemma -> stem
        corpus = load_corpus(corpus_path)
        path = index_path(mode, corpus_path)
        if path.exists() and path.stat().st_mtime >= Path(corpus_path).stat().st_mtime:
            index = BM25Index.load(path)
            if index.N == len(corpus):
                return cls(corpus, index, mode)
        searcher = cls.build(corpus, mode)
        searcher.index.save(path)
        return searcher

    # ------------------------------------------------------------------
    def _card(self, r: dict) -> dict:
        """Поля карточки; у старого корпуса (без КБЖУ/времени) они равны None."""
        return {
            "id": r["id"],
            "title": r["title"],
            "description": r.get("description"),
            "ingredients": r["ingredients"],
            "url": r["url"],
            "categories": r.get("categories", []),
            "total_time_minutes": r.get("total_time_minutes"),
            "portions": r.get("portions"),
            "nutrition_per_100g": r.get("nutrition_per_100g") or dict(EMPTY_NUTRITION),
            "has_steps": r.get("has_steps", False),
        }

    def _ranked(self, query: str, k, require_all: bool, rank: str, filters: dict | None):
        if rank not in {"coverage", "bm25"}:
            raise ValueError(f"unknown rank: {rank}")
        filters = validate_filters(filters)
        q_tokens = self.normalizer.tokens(query)
        cov = rank == "coverage"
        if not any(filters.values()):
            return q_tokens, self.index.search(q_tokens, k, require_all, coverage_first=cov), None
        ranked = [(d, s) for d, s in self.index.search(q_tokens, None, require_all, coverage_first=cov)
                  if matches_filters(self.corpus[d], filters)]
        total = len(ranked)
        return q_tokens, (ranked if k is None else ranked[:k]), total

    def search(self, query: str, k: int | None = 5, require_all: bool = False,
               rank: str = "coverage", filters: dict | None = None) -> list[dict]:
        """Карточки рецептов по запросу.

        k=None — все найденные; require_all=True — только рецепты со всеми продуктами запроса.
        rank="coverage" (по умолчанию) — сначала рецепты, где совпало больше продуктов из запроса,
        при равенстве — по BM25; rank="bm25" — чистый BM25.
        filters — КБЖУ на 100 г и максимальное время (формат как в contracts.md); применяются
        ко всем найденным рецептам до отбора top-k.
        """
        return self.select(query, k, require_all, rank, filters)["items"]

    def select(self, query: str, k: int | None = 5, require_all: bool = False,
               rank: str = "coverage", filters: dict | None = None) -> dict:
        """То же, что search, плюс total — сколько рецептов прошло фильтры (до отбора top-k)."""
        q_tokens, ranked, total = self._ranked(query, k, require_all, rank, filters)
        q_set = set(q_tokens)
        items = []
        for doc_id, score in ranked:
            r = self.corpus[doc_id]
            doc_terms = set(self.normalizer.tokens(doc_text(r)))
            items.append({
                **self._card(r),
                "score": round(score, 4),
                "matched_terms": [t for t in dict.fromkeys(q_tokens) if t in doc_terms],
                **self.missing(r, q_set),
            })
        if total is None:
            c = self.count(query)
            total = c["all"] if require_all else c["any"]
        return {"items": items, "total": total}

    def get_recipe(self, recipe_id: int) -> dict | None:
        """Полный рецепт: карточка + шаги приготовления. None — нет такого id."""
        pos = self._by_id.get(recipe_id)
        if pos is None:
            return None
        if self._steps is None:
            self._steps = StepsStore()
        return {**self._card(self.corpus[pos]), "steps": self._steps.get(recipe_id),
                "corpus_version": self.meta.get("corpus_version")}

    def missing(self, recipe: dict, q_set: set[str]) -> dict:
        """Каких продуктов рецепта нет среди названных пользователем.

        Ингредиент считается имеющимся, если хотя бы одно его значимое слово (после той же
        нормализации и синонимов, что и в поиске) есть в запросе: «Филе куриное» покрывается
        словом «курица», «Сыр козий» — словом «сыр». Слова-уточнения (MODIFIERS) не считаются.
        Базовые продукты (PANTRY: соль, вода, чёрный перец, растительное масло, специи) не выводятся.
        """
        missing = []
        for ing in recipe["ingredients"]:
            if ing["name"].lower().replace("ё", "е") in PANTRY:
                continue
            toks = [t for t in self.normalizer.tokens(ing["name"]) if t not in self._modifiers]
            if any(t in q_set for t in toks):
                continue
            missing.append(ing["name"])
        return {"missing_ingredients": missing}

    def count(self, query: str) -> dict:
        """Сколько рецептов содержат хотя бы один / все продукты запроса."""
        q_tokens = self.normalizer.tokens(query)
        cnt = self.index.matched_counts(q_tokens)
        need = len(set(q_tokens))
        return {"any": len(cnt), "all": sum(1 for c in cnt.values() if c == need) if need else 0}


# ---------------------------------------------------------------------------------- CLI
def _range(s: str | None) -> dict | None:
    """«100:300», «:150», «50:» -> {"min":…, "max":…}."""
    if not s:
        return None
    lo, _, hi = s.partition(":")
    return {"min": float(lo) if lo else None, "max": float(hi) if hi else None}


def _fmt_card(i: int, h: dict, n_terms: int) -> str:
    n = h["nutrition_per_100g"]
    kbju = ("КБЖУ/100 г: нет данных" if n["kcal"] is None else
            f"КБЖУ/100 г: {n['kcal']} ккал · Б {n['protein_g']} · Ж {n['fat_g']} · У {n['carbs_g']}")
    t = "время: нет данных" if h["total_time_minutes"] is None else f"время: {h['total_time_minutes']} мин"
    lack = ", ".join(h["missing_ingredients"]) or "все продукты есть"
    ingr = ", ".join(x["name"] for x in h["ingredients"])
    return (f"{i}. [совпало {len(h['matched_terms'])}/{n_terms} | BM25 {h['score']:.2f}] {h['title']}  (id {h['id']})\n"
            f"   {t} · {kbju}\n   Состав: {ingr}\n   Не хватает: {lack}\n   {h['url']}")


def _main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="BM25-поиск рецептов")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="построить и сохранить индекс")
    b.add_argument("--mode", default="lemma", choices=["lemma", "stem", "none"])
    b.add_argument("--k1", type=float, default=1.5)
    b.add_argument("--b", type=float, default=0.75)
    b.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    q = sub.add_parser("query", help="найти рецепты")
    q.add_argument("text")
    q.add_argument("-k", type=int, default=None,
                   help="сколько рецептов показать (по умолчанию 5; с --all — все)")
    q.add_argument("--mode", default="lemma", choices=["lemma", "stem", "none"])
    q.add_argument("--rank", default="coverage", choices=["coverage", "bm25"],
                   help="coverage: сначала больше совпавших продуктов (по умолчанию); bm25: чистый BM25")
    q.add_argument("--all", action="store_true",
                   help="только рецепты, где есть ВСЕ продукты из запроса")
    q.add_argument("--kcal", help="ккал на 100 г, диапазон МИН:МАКС, например :200")
    q.add_argument("--protein", help="белки, г на 100 г, МИН:МАКС")
    q.add_argument("--fat", help="жиры, г на 100 г, МИН:МАКС")
    q.add_argument("--carbs", help="углеводы, г на 100 г, МИН:МАКС")
    q.add_argument("--max-time", type=int, help="максимальное время приготовления, мин")
    q.add_argument("--json", action="store_true")
    q.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    r = sub.add_parser("recipe", help="показать полный рецепт по id")
    r.add_argument("id", type=int)
    r.add_argument("--mode", default="lemma", choices=["lemma", "stem", "none"])
    r.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    args = ap.parse_args(argv)

    if args.cmd == "build":
        t = time.time()
        s = RecipeSearcher.build(load_corpus(args.corpus), args.mode, args.k1, args.b)
        s.index.save(index_path(s.mode, args.corpus))
        print(json.dumps({**s.index.stats(), "mode": s.mode, "seconds": round(time.time() - t, 1)},
                         ensure_ascii=False))
        return

    s = RecipeSearcher.load(args.mode, args.corpus)
    if args.cmd == "recipe":
        rec = s.get_recipe(args.id)
        if rec is None:
            print("Нет рецепта с таким id")
            return
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return

    filters = {k: v for k, v in {"kcal": _range(args.kcal), "protein_g": _range(args.protein),
                                 "fat_g": _range(args.fat), "carbs_g": _range(args.carbs),
                                 "max_total_time_minutes": args.max_time}.items() if v is not None}
    k = args.k if args.k is not None else (None if args.all else 5)
    page = s.select(args.text, k, require_all=args.all, rank=args.rank, filters=filters)
    hits = page["items"]
    if args.json:
        print(json.dumps(page, ensure_ascii=False, indent=2))
        return
    c = s.count(args.text)
    n_terms = len(set(s.normalizer.tokens(args.text)))
    print(f"Запрос: {args.text}\nТермы:  {s.normalizer.tokens(args.text)}  "
          f"(нормализация: {s.mode}, ранжирование: {args.rank})")
    if filters:
        print(f"Фильтры: {filters}")
    print(f"Найдено: {c['all']} рецептов со ВСЕМИ продуктами, {c['any']} — хотя бы с одним"
          + (f"; после фильтров: {page['total']}" if filters else "")
          + f". Показано: {len(hits)}" + (" (только со всеми продуктами)" if args.all else "") + "\n")
    for i, h in enumerate(hits, 1):
        print(_fmt_card(i, h, n_terms))


if __name__ == "__main__":
    _main()
