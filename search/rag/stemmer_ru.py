"""Стеммер Портера (Snowball) для русского языка.

Используется как запасной вариант нормализации, если библиотека
лемматизации pymorphy3 не установлена. Реализация повторяет алгоритм
https://snowballstem.org/algorithms/russian/stemmer.html и не имеет
внешних зависимостей.
"""
from __future__ import annotations

VOWELS = set("аеиоуыэюя")

PERFECTIVE_GERUND_1 = ("вшись", "вши", "в")          # после «а» / «я»
PERFECTIVE_GERUND_2 = ("ившись", "ывшись", "ивши", "ывши", "ив", "ыв")

ADJECTIVE = (
    "ими", "ыми", "его", "ого", "ему", "ому",
    "ее", "ие", "ые", "ое", "ей", "ий", "ый", "ой", "ем", "им", "ым", "ом",
    "их", "ых", "ую", "юю", "ая", "яя", "ою", "ею",
)
PARTICIPLE_1 = ("ем", "нн", "вш", "ющ", "щ")          # после «а» / «я»
PARTICIPLE_2 = ("ивш", "ывш", "ующ")

REFLEXIVE = ("ся", "сь")

VERB_1 = (                                             # после «а» / «я»
    "ете", "йте", "ешь", "нно",
    "ла", "на", "ли", "ем", "ло", "но", "ет", "ют", "ны", "ть",
    "й", "л", "н",
)
VERB_2 = (
    "ейте", "уйте",
    "ила", "ыла", "ена", "ите", "или", "ыли", "ило", "ыло", "ено", "ует",
    "уют", "ены", "ить", "ыть", "ишь",
    "ей", "уй", "ил", "ыл", "им", "ым", "ен", "ят", "ит", "ыт", "ую", "ю",
)
NOUN = (
    "иями", "ями", "ами", "ией", "иям", "ием", "иях",
    "ев", "ов", "ие", "ье", "еи", "ии", "ей", "ой", "ий", "ям", "ем", "ам",
    "ом", "ах", "ях", "ию", "ью", "ия", "ья",
    "а", "е", "и", "й", "о", "у", "ы", "ь", "ю", "я",
)
SUPERLATIVE = ("ейше", "ейш")
DERIVATIONAL = ("ость", "ост")


def _regions(word: str) -> tuple[int, int]:
    """Возвращает начала областей RV и R2."""
    n = len(word)
    rv = n
    for i, ch in enumerate(word):
        if ch in VOWELS:
            rv = i + 1
            break

    def next_region(start: int) -> int:
        for i in range(start + 1, n):
            if word[i] not in VOWELS and word[i - 1] in VOWELS:
                return i + 1
        return n

    r1 = next_region(0)
    r2 = next_region(r1)
    return rv, r2


def _strip(word: str, rv: int, group1=(), group2=()) -> str | None:
    """Удаляет самое длинное окончание из групп внутри RV.

    Окончания группы 1 удаляются только если перед ними стоит «а» или «я»
    (сама буква остаётся). Возвращает None, если ничего не найдено.
    """
    candidates = [(e, 1) for e in group1] + [(e, 2) for e in group2]
    candidates.sort(key=lambda x: -len(x[0]))
    for ending, grp in candidates:
        start = len(word) - len(ending)
        if start < rv or not word.endswith(ending):
            continue
        if grp == 1:
            if start - 1 < rv or word[start - 1] not in "ая":
                continue
        return word[:start]
    return None


def stem(word: str) -> str:
    word = word.lower().replace("ё", "е")
    rv, r2 = _regions(word)

    # Шаг 1
    res = _strip(word, rv, PERFECTIVE_GERUND_1, PERFECTIVE_GERUND_2)
    if res is not None:
        word = res
    else:
        res = _strip(word, rv, (), REFLEXIVE)
        if res is not None:
            word = res
        res = _strip(word, rv, (), ADJECTIVE)
        if res is not None:
            word = res
            res = _strip(word, rv, PARTICIPLE_1, PARTICIPLE_2)
            if res is not None:
                word = res
        else:
            res = _strip(word, rv, VERB_1, VERB_2)
            if res is None:
                res = _strip(word, rv, (), NOUN)
            if res is not None:
                word = res

    # Шаг 2
    if word.endswith("и") and len(word) - 1 >= rv:
        word = word[:-1]

    # Шаг 3
    res = _strip(word, max(rv, r2), (), DERIVATIONAL)
    if res is not None:
        word = res

    # Шаг 4
    if word.endswith("нн") and len(word) - 2 >= rv:
        word = word[:-1]
    else:
        res = _strip(word, rv, (), SUPERLATIVE)
        if res is not None:
            word = res
            if word.endswith("нн") and len(word) - 2 >= rv:
                word = word[:-1]
        elif word.endswith("ь") and len(word) - 1 >= rv:
            word = word[:-1]
    return word
