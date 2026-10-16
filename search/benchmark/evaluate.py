"""Оценка качества поиска: Recall@k и MRR (формулы — раздел 1.5 методички).

    Recall@k = 1/|Q| * sum_i |R_qi ∩ Top_k(q_i)| / |R_qi|
    MRR      = 1/|Q| * sum_i 1 / rank_i     (rank_i — позиция первого релевантного;
                                             если в выдаче его нет, вклад 0)

Запуск:
    python -m benchmark.evaluate                       # режим lemma (или stem без pymorphy3)
    python -m benchmark.evaluate --mode stem --mode none -k 5 -k 10 -k 20
Учитываются только запросы, у которых размечено не меньше 3 релевантных рецептов.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.search import RecipeSearcher  # noqa: E402

QUERIES = Path(__file__).resolve().parent / "queries.json"
MIN_RELEVANT = 3


def recall_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    return len(relevant.intersection(ranked[:k])) / len(relevant)


def reciprocal_rank(ranked: list[int], relevant: set[int]) -> float:
    for pos, doc_id in enumerate(ranked, 1):
        if doc_id in relevant:
            return 1 / pos
    return 0.0


def evaluate(searcher: RecipeSearcher, queries: list[dict], ks: list[int], depth: int = 100,
             rank: str = "coverage") -> dict:
    per_query = []
    for q in queries:
        rel = set(q["relevant"])
        ranked = [h["id"] for h in searcher.search(q["query"], depth, rank=rank)]
        row = {"id": q["id"], "rr": reciprocal_rank(ranked, rel)}
        row.update({f"recall@{k}": recall_at_k(ranked, rel, k) for k in ks})
        per_query.append(row)
    n = len(per_query)
    summary = {"queries": n, "MRR": sum(r["rr"] for r in per_query) / n}
    summary.update({f"Recall@{k}": sum(r[f"recall@{k}"] for r in per_query) / n for k in ks})
    return {"summary": summary, "per_query": per_query}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", action="append", choices=["lemma", "stem", "none"])
    ap.add_argument("-k", type=int, action="append")
    ap.add_argument("--rank", action="append", choices=["coverage", "bm25"])
    ap.add_argument("--queries", type=Path, default=QUERIES)
    ap.add_argument("--per-query", action="store_true")
    args = ap.parse_args(argv)
    modes = args.mode or ["lemma"]
    ks = sorted(set(args.k or [5, 10, 20]))

    data = json.loads(args.queries.read_text(encoding="utf-8"))
    labeled = [q for q in data["queries"] if len(q.get("relevant", [])) >= MIN_RELEVANT]
    skipped = len(data["queries"]) - len(labeled)
    if not labeled:
        print(f"Нет размеченных запросов (нужно >= {MIN_RELEVANT} релевантных на запрос). "
              f"Сначала соберите пул: python -m benchmark.make_pool")
        return
    if skipped:
        print(f"Пропущено неразмеченных запросов: {skipped}")

    ranks = args.rank or ["bm25", "coverage"]
    for mode in modes:
        searcher = RecipeSearcher.load(mode)
        for rank in ranks:
            res = evaluate(searcher, labeled, ks, rank=rank)
            print(f"\n== нормализация: {searcher.mode}, ранжирование: {rank} ==")
            _print(res, args.per_query)


def _print(res: dict, per_query: bool) -> None:
    for name, val in res["summary"].items():
        print(f"{name:>10}: {val:.4f}" if isinstance(val, float) else f"{name:>10}: {val}")
    if per_query:
        for r in res["per_query"]:
            print("  ", r["id"], " ".join(f"{k}={v:.2f}" for k, v in r.items() if k != "id"))


if __name__ == "__main__":
    main()
