import { z } from "zod";
import type { SelectedRecipe, RagValidation } from "../api/types";

export const MAX_JSONL_BYTES = 5 * 1024 * 1024;
export const MAX_JSONL_RECORDS = 1000;
const name = z.string().trim().min(1, "Поле не должно быть пустым");
const number = z.number().finite().nonnegative().nullable().optional();
export const ragRecipeSchema = z.object({
  title: name,
  ingredients: z.array(z.object({ name, amount: name.nullable().optional() })).min(2, "Нужно минимум два ингредиента"),
  url: z.string().url("Нужна ссылка на источник").refine((s) => /^https?:\/\//i.test(s), "Источник должен использовать HTTP/HTTPS"),
  description: name.nullable().optional(),
  steps: z.array(name).optional(),
  nutrition_per_100g: z.object({ kcal: number, protein_g: number, fat_g: number, carbs_g: number }).optional(),
  total_time_minutes: z.number().int().positive().nullable().optional(),
  id: z.number().int().optional(),
  source: z.string().optional(),
});
export type RagRecipeInput = z.infer<typeof ragRecipeSchema>;
const canonical = (s: string) => s.trim().toLowerCase().replace(/ё/g, "е").replace(/\s+/g, " ");
export function recipeKey(r: Pick<RagRecipeInput, "title" | "ingredients">): string {
  return JSON.stringify([canonical(r.title), [...new Set(r.ingredients.map((i) => canonical(i.name)))].sort()]);
}
export function validateJsonl(text: string, existing: SelectedRecipe[]): RagValidation & { records: RagRecipeInput[] } {
  const result: RagValidation & { records: RagRecipeInput[] } = { count: 0, errors: [], duplicates: [], valid: false, records: [] };
  if (new TextEncoder().encode(text).byteLength > MAX_JSONL_BYTES) {
    result.errors.push({ line: 1, message: "Файл превышает 5 МиБ" });
    return result;
  }
  const keys = new Set(existing.map(recipeKey));
  for (const [index, raw] of text.replace(/^\uFEFF/, "").split(/\r?\n/).entries()) {
    if (!raw.trim()) continue;
    result.count++;
    if (result.count > MAX_JSONL_RECORDS) {
      result.errors.push({ line: index + 1, message: "Не более 1000 записей" });
      break;
    }
    try {
      const parsed = ragRecipeSchema.safeParse(JSON.parse(raw));
      if (!parsed.success) {
        result.errors.push({ line: index + 1, message: parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; ") });
        continue;
      }
      const key = recipeKey(parsed.data);
      if (keys.has(key)) result.duplicates.push({ line: index + 1, message: "Рецепт уже существует или повторён в файле" });
      keys.add(key);
      result.records.push(parsed.data);
    } catch {
      result.errors.push({ line: index + 1, message: "Некорректный JSON" });
    }
  }
  if (!result.count) result.errors.push({ line: 1, message: "Файл не содержит записей" });
  result.valid = !result.errors.length && !result.duplicates.length;
  return result;
}
