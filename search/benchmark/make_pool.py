"""Сбор пула кандидатов для ручной разметки релевантности (pooling).

Для каждого запроса объединяются top-N выдачи нескольких вариантов системы
(разные режимы нормализации). Разметчик проставляет в CSV 1/0 в колонке
relevant, затем apply_labels переносит id релевантных рецептов в queries.json.

    python -m benchmark.make_pool --modes stem none -n 20     # -> benchmark/pool.csv
    (разметить колонку relevant в pool.csv)
    python -m benchmark.make_pool --status                    # прогресс разметки
    python -m benchmark.make_pool --apply                     # pool.csv -> queries.json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.search import RecipeSearcher  # noqa: E402

HERE = Path(__file__).resolve().parent
QUERIES = HERE / "queries.json"
POOL = HERE / "pool.csv"
POSITIVE = {"1", "1.0", "да", "+", "y", "yes"}
NEGATIVE = {"0", "0.0", "нет", "-", "n", "no"}


def make_pool(modes: list[str], n: int, force: bool = False) -> None:
    if POOL.exists() and not force and any(r["relevant"] for r in read_pool()):
        sys.exit(f"В {POOL.name} уже есть разметка — не перезаписываю. "
                 f"Если точно нужно собрать пул заново, добавьте --force (разметка пропадёт).")
    data = json.loads(QUERIES.read_text(encoding="utf-8"))
    searchers = [RecipeSearcher.load(m) for m in modes]
    by_id = {r["id"]: r for r in searchers[0].corpus}
    with open(POOL, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["query_id", "query", "criterion", "recipe_id", "title", "ingredients", "url", "relevant"])
        for q in data["queries"]:
            pool: dict[int, None] = {}
            for s in searchers:
                for rank in ("bm25", "coverage"):
                    for h in s.search(q["query"], n, rank=rank):
                        pool.setdefault(h["id"], None)
            for rid in pool:
                r = by_id[rid]
                w.writerow([q["id"], q["query"], q["criterion"], rid, r["title"],
                            ", ".join(i["name"] for i in r["ingredients"]), r["url"], ""])
    print(f"Пул записан в {POOL}. Заполните колонку relevant (1 — релевантен, 0 — нет).")


def read_pool() -> list[dict]:
    """Читает pool.csv после Excel: кодировка UTF-8 или Windows-1251, разделитель «;» / «,» / Tab."""
    raw = POOL.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    first = text.splitlines()[0] if text else ""
    delim = max([";", ",", "\t"], key=first.count)
    rows = list(csv.DictReader(io.StringIO(text, newline=""), delimiter=delim))
    for r in rows:
        r["relevant"] = (r.get("relevant") or "").strip().lower()
    return rows


def status() -> None:
    rows = read_pool()
    by_q: dict[str, list[dict]] = {}
    for r in rows:
        by_q.setdefault(r["query_id"], []).append(r)
    done = sum(1 for r in rows if r["relevant"] in POSITIVE | NEGATIVE)
    print(f"Размечено строк: {done} из {len(rows)}\n")
    print("запрос  размечено  релевантных")
    for qid, rs in by_q.items():
        d = sum(1 for r in rs if r["relevant"] in POSITIVE | NEGATIVE)
        pos = sum(1 for r in rs if r["relevant"] in POSITIVE)
        warn = "  <- меньше 3 релевантных" if d == len(rs) and pos < 3 else ""
        print(f"{qid:>6}  {d:>4}/{len(rs):<4}  {pos:>5}{warn}")
    bad = sorted({r["relevant"] for r in rows if r["relevant"] and r["relevant"] not in POSITIVE | NEGATIVE})
    if bad:
        print(f"\nНепонятные значения в relevant: {bad} (нужно 1 или 0)")


def apply_labels() -> None:
    """Переносит разметку из pool.csv в queries.json (pool.csv — источник истины)."""
    data = json.loads(QUERIES.read_text(encoding="utf-8"))
    rel: dict[str, set[int]] = {}
    for row in read_pool():
        if row["relevant"] in POSITIVE:
            rel.setdefault(row["query_id"], set()).add(int(float(row["recipe_id"])))
    for q in data["queries"]:
        q["relevant"] = sorted(rel.get(q["id"], set()))
    QUERIES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    few = [q["id"] for q in data["queries"] if len(q["relevant"]) < 3]
    print("Разметка перенесена в queries.json." + (f" Меньше 3 релевантных: {few}" if few else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="+", default=["lemma", "none"])
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--apply", action="store_true", help="перенести разметку в queries.json")
    ap.add_argument("--status", action="store_true", help="показать прогресс разметки")
    ap.add_argument("--force", action="store_true", help="пересобрать пул, даже если он размечен")
    a = ap.parse_args()
    if a.apply:
        apply_labels()
    elif a.status:
        status()
    else:
        make_pool(a.modes, a.n, a.force)
