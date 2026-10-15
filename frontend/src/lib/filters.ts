import type { Filters, Recipe, NutritionKey } from "../api/types";
export const nutritionFields: [NutritionKey, string][] = [
  ["kcal", "Калории, ккал"],
  ["protein_g", "Белки, г"],
  ["fat_g", "Жиры, г"],
  ["carbs_g", "Углеводы, г"],
];
export function validateFilters(f: Filters): string | null {
  for (const [key, label] of nutritionFields) {
    const r = f[key];
    if (!r) continue;
    for (const v of [r.min, r.max])
      if (v != null && (!Number.isFinite(v) || v < 0))
        return label + ": введите неотрицательное число";
    if (r.min != null && r.max != null && r.min > r.max)
      return label + ": минимум больше максимума";
  }
  const t = f.max_total_time_minutes;
  if (t != null && (!Number.isInteger(t) || t <= 0))
    return "Время должно быть положительным целым числом";
  return null;
}
export function matchesFilters(r: Recipe, f: Filters): boolean {
  for (const [key] of nutritionFields) {
    const range = f[key];
    if (range && (range.min != null || range.max != null)) {
      const v = r.nutrition_per_100g[key];
      if (
        v == null ||
        (range.min != null && v < range.min) ||
        (range.max != null && v > range.max)
      )
        return false;
    }
  }
  return (
    f.max_total_time_minutes == null ||
    (r.total_time_minutes != null &&
      r.total_time_minutes <= f.max_total_time_minutes)
  );
}
export const difficultyLabel = (v: Recipe["difficulty"]) =>
  v == null
    ? "нет данных"
    : { easy: "Легко", medium: "Средне", hard: "Сложно" }[v];
