"""Поиск в фиксированном учебном корпусе и подготовка контекста для генератора."""
import json
from pathlib import Path
from statistics import mean

from benchmark.evaluate import recall_at_k, reciprocal_rank
from rag.search import RecipeSearcher

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def main():
    docs = read("documents.json")
    questions = read("questions.json")
    by_id = {r["id"]: r for r in docs}
    search = RecipeSearcher.build(docs, mode="lemma")
    if search.mode != "lemma":
        raise RuntimeError("Для воспроизведения установите pymorphy3.")
    results = []
    for q in questions:
        ranked = [by_id[h["id"]]["doc_id"] for h in search.search(q["question"], k=30)]
        row = dict(id=q["id"], question=q["question"], top5=ranked[:5], ranked=ranked)
        if q["relevant"]:
            gold = set(q["relevant"])
            row["Recall@5"] = recall_at_k(ranked, gold, 5)
            row["MRR@30"] = reciprocal_rank(ranked, gold)
        results.append(row)
    ordinary = [row for row in results if "Recall@5" in row]
    summary = {key: mean(r[key] for r in ordinary) for key in ("Recall@5", "MRR@30")}
    output = dict(summary=summary, results=results)
    (HERE / "small_results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
