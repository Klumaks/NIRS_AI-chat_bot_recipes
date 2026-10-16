"""Конвертация датасета d0rj/povarenok_recipes_detail из parquet в JSONL.

Нужен pyarrow:  py -m pip install pyarrow
Запуск:         py -m rag.convert_parquet
Читает data/raw/*.parquet, пишет data/raw/povarenok_detail.jsonl (одна строка = один рецепт).
Ссылки на фотографии отбрасываются — они не нужны поиску и сильно увеличивают файл.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT = RAW / "povarenok_detail.jsonl"
KEEP = [
    "title", "page_url", "description", "ingredients", "cooking_time", "portions_count",
    "cooking_steps", "kroshki", "tags", "purposes", "tastes", "nae_value", "views",
    "creation_datetime",
]


def main() -> None:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        sys.exit("Нужна библиотека pyarrow. Установите: py -m pip install pyarrow")
    files = sorted(RAW.glob("*.parquet"))
    if not files:
        sys.exit(f"В {RAW} нет файлов .parquet")
    n = 0
    with open(OUT, "w", encoding="utf-8") as out:
        for path in files:
            pf = pq.ParquetFile(path)
            cols = [c for c in KEEP if c in pf.schema_arrow.names]
            for batch in pf.iter_batches(batch_size=2000, columns=cols):
                for row in batch.to_pylist():
                    out.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                    n += 1
            print(f"{path.name}: готово, всего строк {n}")
    print(f"Записано {n} рецептов в {OUT} ({OUT.stat().st_size / 1e6:.0f} МБ)")


if __name__ == "__main__":
    main()
