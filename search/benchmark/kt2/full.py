"""Повтор эксперимента на полном корпусе проекта."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean

from benchmark.evaluate import recall_at_k, reciprocal_rank
from rag.bm25 import BM25Index
from rag.corpus import doc_text
from rag.text import get_normalizer

HERE = Path(__file__).resolve().parent
KS = (5, 10, 20)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('data', type=Path, help='Каталог с corpus.jsonl и индексами')
    args = parser.parse_args()
    corpus = args.data / 'corpus.jsonl'
    source = HERE.parent / 'queries.json'
    queries = json.loads(source.read_text(encoding='utf-8'))['queries']
    ids = []
    with corpus.open(encoding='utf-8') as stream:
        for line in stream:
            ids.append(json.loads(line)['id'])
    manifest = {p.name: digest(p) for p in [corpus, source, HERE.parent / 'pool.csv', Path(__file__), *sorted((HERE.parents[1] / 'rag').glob('*.py'))]}
    details = []
    for mode in ('lemma', 'stem', 'none'):
        norm = get_normalizer(mode)
        assert norm.mode == mode
        path = args.data / f'index_corpus_{mode}.pkl'
        if path.exists():
            index = BM25Index.load(path)
        else:
            with corpus.open(encoding='utf-8') as stream:
                index = BM25Index().build(norm.tokens(doc_text(json.loads(line))) for line in stream)
            index.save(path)
        assert index.N == len(ids)
        manifest[path.name] = digest(path)
        for k1 in (1.2, 1.5, 2.0):
            for b in (0.5, 0.75, 1.0):
                index.k1, index.b = k1, b
                for rank in ('coverage', 'bm25'):
                    for q in queries:
                        relevant = set(q['relevant'])
                        assert len(relevant) >= 3
                        hits = index.search(norm.tokens(q['query']), 100, coverage_first=rank == 'coverage')
                        ranked = [ids[i] for i, score in hits]
                        row = dict(mode=mode, rank=rank, k1=k1, b=b, query=q['id'])
                        row.update({f'Recall@{k}': recall_at_k(ranked, relevant, k) for k in KS})
                        row['MRR@100'] = reciprocal_rank(ranked, relevant)
                        row['top100'] = ' '.join(map(str, ranked))
                        details.append(row)
    fields = ('mode', 'rank', 'k1', 'b')
    metrics = ('Recall@5', 'Recall@10', 'Recall@20', 'MRR@100')
    grouped = {}
    for row in details:
        grouped.setdefault(tuple(row[k] for k in fields), []).append(row)
    summary = [dict(zip(fields, key), **{m: mean(r[m] for r in block) for m in metrics})
               for key, block in grouped.items()]
    for name, records in [('full_results.csv', details), ('comparison.csv', summary)]:
        with (HERE / name).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=records[0])
            writer.writeheader()
            writer.writerows(records)
    (HERE / 'versions.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
