"""Тесты модуля поиска. Запуск: python -m pytest tests  (или python tests/test_rag.py)."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.bm25 import BM25Index  # noqa: E402
from rag.corpus import clean_ingredient_name, parse_ingredients  # noqa: E402
from rag.stemmer_ru import stem  # noqa: E402
from rag.text import Normalizer  # noqa: E402
from benchmark.evaluate import recall_at_k, reciprocal_rank  # noqa: E402

# Пример из методички (раздел 1.4), уже после предобработки.
DOCS = [
    ["лапласиан", "граф", "использоваться", "анализ", "структура"],
    ["матрица", "смежность", "граф", "описывать", "связь", "вершина"],
    ["метод", "машинный", "обучение", "использовать", "матрица", "данные"],
]


def test_inverted_index_matches_example():
    idx = BM25Index().build(DOCS)
    docs_of = lambda t: [d for d, _ in idx.postings[t]]  # noqa: E731
    assert docs_of("лапласиан") == [0]
    assert docs_of("граф") == [0, 1]
    assert docs_of("матрица") == [1, 2]
    assert docs_of("обучение") == [2]


def test_bm25_formula_by_hand():
    k1, b = 1.5, 0.75
    idx = BM25Index(k1, b).build(DOCS)
    N, avgdl = 3, (5 + 6 + 6) / 3
    idf = math.log(1 + (N - 2 + 0.5) / (2 + 0.5))  # DF(граф) = 2
    expected = idf * 1 * (k1 + 1) / (1 + k1 * (1 - b + b * 5 / avgdl))
    assert math.isclose(idx.scores(["граф"])[0], expected)


def test_ranking_order_and_absent_terms():
    idx = BM25Index().build(DOCS)
    top = idx.search(["матрица", "граф"], k=3)
    assert top[0][0] == 1                     # d2 содержит оба терма
    assert {d for d, _ in top} == {0, 1, 2}
    assert idx.search(["несуществующий"], k=3) == []


def test_require_all_and_unlimited():
    idx = BM25Index().build(DOCS)
    assert [d for d, _ in idx.search(["матрица", "граф"], k=None, require_all=True)] == [1]
    assert len(idx.search(["матрица", "граф"], k=None)) == 3
    assert idx.search(["граф", "несуществующий"], k=None, require_all=True) == []


def test_coverage_first_ranking():
    filler = [f"x{i}" for i in range(30)]
    docs = [["сыр"], ["томат", "сыр", "вино"] + filler, ["томат"]]
    idx = BM25Index().build(docs)
    q = ["томат", "сыр", "вино"]
    assert idx.search(q, k=1, coverage_first=True)[0][0] == 1   # все 3 продукта — первым
    by_cov = idx.search(q, k=None, coverage_first=True)
    assert [d for d, _ in by_cov][1:] == [d for d, _ in idx.search(["томат", "сыр"], k=None) if d != 1]


def test_missing_ingredients():
    from rag.search import RecipeSearcher
    corpus = [{"id": 7, "title": "Рис с курицей", "url": "u", "ingredients": [
        {"name": "Филе куриное", "amount": "300 г"}, {"name": "Рис", "amount": None},
        {"name": "Морковь", "amount": "1 шт"}, {"name": "Соль", "amount": None},
        {"name": "Перец черный", "amount": None}]}]
    s = RecipeSearcher.build(corpus, mode="stem")
    hit = s.search("курица, рис, черный хлеб", k=1)[0]
    assert hit["missing_ingredients"] == ["Морковь"]          # соль и перец не выводятся
    assert "missing_basics" not in hit


def test_detail_parsing():
    from rag.corpus import parse_nutrition, parse_time
    assert parse_time("40 минут") == 40
    assert parse_time(None) is None and parse_time("0 минут") is None
    assert parse_time("10368000 минут") is None                 # больше 30 суток — ошибка ввода
    nae = {"100 г блюда": {"carb": 3.0, "fats": 7.7, "kcal": 133.2, "protein": 9.4}}
    assert parse_nutrition(nae) == {"kcal": 133.2, "protein_g": 9.4, "fat_g": 7.7, "carbs_g": 3.0}
    zeros = {"100 г блюда": {"carb": 0, "fats": 0, "kcal": 0, "protein": 0}}
    assert parse_nutrition(zeros)["kcal"] is None                # калькулятор сайта не посчитал
    assert parse_nutrition({"100 г блюда": {"carb": 1, "fats": 1, "kcal": 5000, "protein": 1}})["kcal"] is None


def test_filters():
    from rag.search import RecipeSearcher, matches_filters, validate_filters
    r = {"nutrition_per_100g": {"kcal": 150.0, "protein_g": 10.0, "fat_g": 5.0, "carbs_g": 20.0},
         "total_time_minutes": 30}
    assert matches_filters(r, {"kcal": {"max": 150}, "max_total_time_minutes": 30})   # границы включаются
    assert not matches_filters(r, {"max_total_time_minutes": 29})
    assert not matches_filters({**r, "total_time_minutes": None}, {"max_total_time_minutes": 60})
    assert matches_filters({**r, "total_time_minutes": None}, {"kcal": {"min": None, "max": None}})
    for bad in ({"kcal": {"min": 10, "max": 5}}, {"fat_g": {"min": -1}}, {"max_total_time_minutes": 0}):
        try:
            validate_filters(bad)
            assert False, bad
        except ValueError:
            pass
    corpus = [{"id": 0, "title": "Рис с курицей", "url": "u", "ingredients": [
                  {"name": "Курица", "amount": None}, {"name": "Рис", "amount": None}], **r},
              {"id": 1, "title": "Плов с курицей", "url": "u", "ingredients": [
                  {"name": "Курица", "amount": None}, {"name": "Рис", "amount": None}],
               "nutrition_per_100g": {"kcal": 300.0, "protein_g": 10.0, "fat_g": 15.0, "carbs_g": 30.0},
               "total_time_minutes": 90}]
    s = RecipeSearcher.build(corpus, mode="stem")
    page = s.select("курица рис", k=5, filters={"kcal": {"max": 200}})
    assert [h["id"] for h in page["items"]] == [0] and page["total"] == 1
    assert s.select("курица рис", k=1)["total"] == 2


def test_idf_positive_even_for_frequent_terms():
    idx = BM25Index().build([["соль"]] * 10)
    assert idx.idf["соль"] > 0


def test_porter_stemmer():
    assert stem("картошкой") == stem("картошка")
    assert stem("помидоры") == stem("помидор")
    assert stem("яйцами") == stem("яйца")


def test_normalizer_drops_stopwords_and_maps_synonyms():
    n = Normalizer("stem")
    toks = n.tokens("Что приготовить из картошки и 2 яиц?")
    assert "что" not in toks and n.word("картофель") in toks


def test_parse_and_clean_ingredients():
    ingr = parse_ingredients("{'Яйцо куриное': '5 шт', 'Сыр твердый': None, 'Капуста белокочанная': '1 кг'}")
    assert [i["name"] for i in ingr] == ["Яйцо", "Сыр твердый", "Капуста белокочанная"]
    assert ingr[1]["amount"] is None
    assert clean_ingredient_name("Филе куриное") == "Филе куриное"
    assert parse_ingredients("not a dict") == []


def test_metrics():
    ranked = [7, 3, 9, 1, 5]
    rel = {3, 5, 8}
    assert math.isclose(recall_at_k(ranked, rel, 2), 1 / 3)
    assert math.isclose(recall_at_k(ranked, rel, 5), 2 / 3)
    assert reciprocal_rank(ranked, rel) == 0.5
    assert reciprocal_rank(ranked, {42}) == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
