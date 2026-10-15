import type { SelectedRecipe } from "../api/types";
const provenance = Object.fromEntries(
  [
    "description",
    "steps",
    "kcal",
    "protein_g",
    "fat_g",
    "carbs_g",
    "total_time_minutes",
    "difficulty",
  ].map((k) => [
    k,
    {
      source_ref: "Демонстрационный набор КТ1",
      method: "editorial",
      checked_by: "Учебная фикстура — не источник пищевой ценности",
      checked_at: "2026-01-01T00:00:00Z",
    },
  ]),
);
const base = {
  url: "https://www.povarenok.ru/recipes/",
  provenance,
  data_mode: "demo" as const,
  corpus_version: "demo-corpus-v1",
  verified_version: "demo-recipes-v1",
  missing_ingredients: [],
};
export const recipes: SelectedRecipe[] = [
  {
    ...base,
    recipe_id: 1,
    verified_version: "demo-recipes-v2",
    title: "Рис с курицей и овощами",
    description:
      "Простой ужин в одной сковороде. Нежная курица и рассыпчатый рис.",
    ingredients: [
      { name: "Курица", amount: "300 г" },
      { name: "Рис", amount: "150 г" },
      { name: "Лук", amount: "1 шт." },
      { name: "Морковь", amount: "1 шт." },
      { name: "Масло", amount: "1 ст. л." },
      { name: "Вода", amount: "300 мл" },
    ],
    nutrition_per_100g: { kcal: 165, protein_g: 12, fat_g: 5, carbs_g: 18 },
    total_time_minutes: 25,
    difficulty: "easy",
    steps: [
      "Нарежьте курицу и овощи. Обжарьте на масле.",
      "Добавьте промытый рис и воду, накройте крышкой.",
      "Готовьте до мягкости риса и полной готовности курицы.",
    ],
  },
  {
    ...base,
    recipe_id: 2,
    title: "Куриный суп с рисом",
    description: "Лёгкий домашний суп с овощами и ароматным бульоном.",
    ingredients: [
      { name: "Курица", amount: "250 г" },
      { name: "Рис", amount: "80 г" },
      { name: "Лук", amount: "1 шт." },
      { name: "Морковь", amount: "1 шт." },
      { name: "Картофель", amount: "2 шт." },
      { name: "Вода", amount: "1,5 л" },
    ],
    nutrition_per_100g: { kcal: 85, protein_g: 6, fat_g: 3, carbs_g: 9 },
    total_time_minutes: 40,
    difficulty: "easy",
    steps: [
      "Подготовьте курицу, крупу и овощи.",
      "Сварите курицу в воде. Добавьте рис и овощи.",
      "Доведите все ингредиенты до полной готовности.",
    ],
  },
  {
    ...base,
    recipe_id: 3,
    title: "Рисовые котлеты с курицей",
    description: "Золотистые котлеты, которые удобно подать с овощами.",
    ingredients: [
      { name: "Курица", amount: "300 г" },
      { name: "Рис", amount: "100 г" },
      { name: "Лук", amount: "1 шт." },
      { name: "Яйцо", amount: "1 шт." },
      { name: "Масло", amount: "1 ст. л." },
    ],
    nutrition_per_100g: { kcal: 180, protein_g: 14, fat_g: 7, carbs_g: 15 },
    total_time_minutes: 35,
    difficulty: "medium",
    steps: [
      "Отварите рис и измельчите курицу с луком.",
      "Смешайте с яйцом и сформируйте котлеты.",
      "Обжарьте до полной готовности.",
    ],
  },
  {
    ...base,
    recipe_id: 4,
    title: "Омлет с помидорами",
    description: "Быстрый и уютный завтрак из самых простых продуктов.",
    ingredients: [
      { name: "Яйцо", amount: "2 шт." },
      { name: "Помидор", amount: "1 шт." },
      { name: "Молоко", amount: "40 мл" },
      { name: "Масло", amount: "1 ч. л." },
    ],
    nutrition_per_100g: { kcal: 135, protein_g: 9, fat_g: 9, carbs_g: 4 },
    total_time_minutes: 15,
    difficulty: "easy",
    steps: [
      "Нарежьте помидор, взбейте яйца с молоком.",
      "Обжарьте помидор, добавьте яичную смесь.",
      "Готовьте под крышкой до готовности.",
    ],
  },
  {
    ...base,
    recipe_id: 5,
    title: "Рис с зеленью",
    description: "Простой гарнир. Часть параметров в примере не указана.",
    ingredients: [
      { name: "Рис", amount: "150 г" },
      { name: "Вода", amount: null },
      { name: "Зелень", amount: null },
    ],
    nutrition_per_100g: {
      kcal: null,
      protein_g: null,
      fat_g: null,
      carbs_g: null,
    },
    total_time_minutes: null,
    difficulty: null,
    steps: [
      "Промойте рис и приготовьте его до мягкости.",
      "Добавьте измельчённую зелень.",
    ],
  },
  {
    ...base,
    recipe_id: 6,
    title: "Картофель с луком",
    description: "Домашний гарнир с золотистым луком.",
    ingredients: [
      { name: "Картофель", amount: "400 г" },
      { name: "Лук", amount: "1 шт." },
      { name: "Масло", amount: "1 ст. л." },
    ],
    nutrition_per_100g: { kcal: 140, protein_g: 3, fat_g: 5, carbs_g: 21 },
    total_time_minutes: 30,
    difficulty: "easy",
    steps: [
      "Подготовьте картофель и лук.",
      "Обжарьте на масле и доведите до готовности.",
    ],
  },
  {
    ...base,
    recipe_id: 7,
    title: "Курица: неполный рецепт",
    description: "Пример записи, в которой отсутствуют шаги приготовления.",
    ingredients: [{ name: "Курица", amount: "300 г" }],
    nutrition_per_100g: {
      kcal: null,
      protein_g: null,
      fat_g: null,
      carbs_g: null,
    },
    total_time_minutes: null,
    difficulty: null,
    steps: [],
  },
];
export function ingredientTerms(s: string): string[] {
  return s
    .toLowerCase()
    .replace(/ё/g, "е")
    .split(/[^а-яa-z]+/)
    .filter(Boolean)
    .map((w) =>
      w.startsWith("кур")
        ? "курица"
        : w.startsWith("рис")
          ? "рис"
          : w.startsWith("лук")
            ? "лук"
            : w.startsWith("яй")
              ? "яйцо"
              : w.startsWith("помид") || w.startsWith("томат")
                ? "помидор"
                : w.startsWith("карто")
                  ? "картофель"
                  : w.startsWith("морков")
                    ? "морковь"
                    : w.startsWith("масл")
                      ? "масло"
                      : w,
    )
    .filter(
      (w) =>
        ![
          "есть",
          "что",
          "из",
          "и",
          "у",
          "меня",
          "приготовить",
          "с",
          "можно",
        ].includes(w),
    );
}
export function candidates(query: string): SelectedRecipe[] {
  const q = ingredientTerms(query);
  return recipes
    .filter(
      (r) =>
        r.recipe_id !== 7 &&
        r.ingredients.some((i) =>
          ingredientTerms(i.name).some((t) => q.includes(t)),
        ),
    )
    .map((r) => ({
      ...structuredClone(r),
      missing_ingredients: r.ingredients
        .filter((i) => !ingredientTerms(i.name).some((t) => q.includes(t)))
        .map((i) => i.name),
    }));
}
