"""Собственная реализация поискового индекса BM25 (без готовых поисковых библиотек).

Индекс — обратный (inverted index): терм -> список пар (номер документа, TF).
Формулы — по методичке:

    IDF(t)      = ln(1 + (N - DF(t) + 0.5) / (DF(t) + 0.5))
    BM25(q, d)  = sum_{t in q} IDF(t) * TF(t,d) * (k1 + 1)
                  / (TF(t,d) + k1 * (1 - b + b * |d| / avgdl))
"""
from __future__ import annotations

import heapq
import math
import pickle
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Sequence


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.postings: dict[str, list[tuple[int, int]]] = {}
        self.doc_len: list[int] = []
        self.idf: dict[str, float] = {}
        self.N = 0
        self.avgdl = 0.0

    # ------------------------------------------------------------ построение
    def build(self, docs_tokens: Iterable[Sequence[str]]) -> "BM25Index":
        """docs_tokens — последовательность уже предобработанных документов."""
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        doc_len: list[int] = []
        for doc_id, tokens in enumerate(docs_tokens):
            doc_len.append(len(tokens))
            for term, tf in Counter(tokens).items():
                postings[term].append((doc_id, tf))
        self.postings = dict(postings)
        self.doc_len = doc_len
        self.N = len(doc_len)
        self.avgdl = (sum(doc_len) / self.N) if self.N else 0.0
        self.idf = {t: self._idf(len(p)) for t, p in self.postings.items()}
        return self

    def _idf(self, df: int) -> float:
        return math.log(1 + (self.N - df + 0.5) / (df + 0.5))

    # ------------------------------------------------------------------ поиск
    def scores(self, query_tokens: Sequence[str]) -> dict[int, float]:
        """BM25 для всех документов, содержащих хотя бы один терм запроса.

        Документы без общих термов имеют BM25 = 0 и в результат не попадают.
        Суммирование идёт по кортежу термов запроса, т.е. повтор терма
        в запросе учитывается повторно (как в формуле).
        """
        k1, b, avgdl = self.k1, self.b, self.avgdl
        acc: dict[int, float] = defaultdict(float)
        for term in query_tokens:
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = self.idf[term]
            for doc_id, tf in plist:
                norm = k1 * (1 - b + b * self.doc_len[doc_id] / avgdl)
                acc[doc_id] += idf * tf * (k1 + 1) / (tf + norm)
        return acc

    def matched_counts(self, query_tokens: Sequence[str]) -> dict[int, int]:
        """Сколько разных термов запроса содержит каждый документ."""
        cnt: dict[int, int] = defaultdict(int)
        for term in set(query_tokens):
            for doc_id, _ in self.postings.get(term, ()):
                cnt[doc_id] += 1
        return cnt

    def search(self, query_tokens: Sequence[str], k: int | None = 10,
               require_all: bool = False, coverage_first: bool = False) -> list[tuple[int, float]]:
        """Документы по невозрастанию BM25 (при равенстве — меньший id выше).

        k=None — вернуть все найденные документы, а не только top-k.
        require_all=True — оставить только документы, содержащие ВСЕ термы запроса.
        coverage_first=True — сначала документы, где совпало больше разных термов запроса,
        внутри группы — по BM25 (переранжирование по покрытию запроса).
        """
        acc = self.scores(query_tokens)
        cnt = self.matched_counts(query_tokens) if (require_all or coverage_first) else {}
        if require_all:
            need = len(set(query_tokens))
            acc = {d: s for d, s in acc.items() if cnt[d] == need}
        if coverage_first:
            key = lambda x: (-cnt[x[0]], -x[1], x[0])  # noqa: E731
        else:
            key = lambda x: (-x[1], x[0])  # noqa: E731
        if k is None:
            return sorted(acc.items(), key=key)
        return heapq.nsmallest(k, acc.items(), key=key)

    # ------------------------------------------------------- сохранение/загрузка
    def save(self, path: str | Path) -> None:
        with open(path, "wb") as f:
            pickle.dump(
                {"k1": self.k1, "b": self.b, "postings": self.postings, "doc_len": self.doc_len},
                f,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

    @classmethod
    def load(cls, path: str | Path) -> "BM25Index":
        with open(path, "rb") as f:
            data = pickle.load(f)
        idx = cls(k1=data["k1"], b=data["b"])
        idx.postings = data["postings"]
        idx.doc_len = data["doc_len"]
        idx.N = len(idx.doc_len)
        idx.avgdl = sum(idx.doc_len) / idx.N if idx.N else 0.0
        idx.idf = {t: idx._idf(len(p)) for t, p in idx.postings.items()}
        return idx

    # -------------------------------------------------------------- отладка
    def stats(self) -> dict:
        return {"documents": self.N, "terms": len(self.postings), "avgdl": round(self.avgdl, 2),
                "k1": self.k1, "b": self.b}
