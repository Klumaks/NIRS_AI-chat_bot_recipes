import { useState } from "react";
import type { SelectedRecipe } from "../api/types";
import type { RagRecipeInput } from "../lib/rag";
import { ragRecipeSchema } from "../lib/rag";
import { nutritionFields } from "../lib/filters";
import { ErrorBox } from "../components/UI";

export function RagRecipeForm({ initial, onSave, onCancel, disabled, saving, error }: {
  initial: SelectedRecipe | null;
  onSave: (input: RagRecipeInput) => void;
  onCancel: () => void;
  disabled: boolean;
  saving: boolean;
  error: unknown;
}) {
  const [formError, setFormError] = useState("");
  const [ingredients, setIngredients] = useState(() => {
    const values = initial?.ingredients.map((i) => ({ name: i.name, amount: i.amount ?? "" })) ?? [];
    while (values.length < 2) values.push({ name: "", amount: "" });
    return values;
  });
  return (
        <form className="rag-panel" onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const string = (key: string) => String(data.get(key) ?? "").trim();
          const numeric = (key: string) => string(key) === "" ? null : Number(string(key));
          const parsed = ragRecipeSchema.safeParse({
            title: string("title"), url: string("url"), description: string("description") || null,
            ingredients: ingredients.map((i) => ({ name: i.name, amount: i.amount.trim() || null })),
            steps: string("steps").split(/\r?\n/).map((s) => s.trim()).filter(Boolean),
            nutrition_per_100g: Object.fromEntries(nutritionFields.map(([key]) => [key, numeric(key)])),
            total_time_minutes: numeric("time"),
          });
          if (!parsed.success) { setFormError(parsed.error.issues.map((i) => i.message).join("; ")); return; }
          setFormError("");
          onSave(parsed.data);
        }}>
          <h2>{initial ? "Редактирование рецепта" : "Новый рецепт"}</h2>
          <fieldset disabled={disabled} className="rag-fields">
            <label>Название<input name="title" defaultValue={initial?.title} required autoFocus={!!initial} /></label>
            <label>Источник (HTTP/HTTPS)<input name="url" type="url" defaultValue={initial?.url} required /></label>
            <div>
              <h3>Ингредиенты</h3>
              <p className="muted small">Минимум два. Количество можно не указывать.</p>
              {ingredients.map((ingredient, index) => (
                <div className="rag-ingredient" key={index}>
                  <label>Продукт {index + 1}<input required value={ingredient.name} onChange={(e) => setIngredients((items) => items.map((item, i) => i === index ? { ...item, name: e.target.value } : item))} /></label>
                  <label>Количество {index + 1}<input value={ingredient.amount} onChange={(e) => setIngredients((items) => items.map((item, i) => i === index ? { ...item, amount: e.target.value } : item))} /></label>
                  {ingredients.length > 2 && <button type="button" className="text-button" aria-label={`Удалить ингредиент ${index + 1}`} onClick={() => setIngredients((items) => items.filter((_, i) => i !== index))}>Удалить</button>}
                </div>
              ))}
              <button type="button" className="text-button" onClick={() => setIngredients((items) => [...items, { name: "", amount: "" }])}>Добавить ингредиент</button>
            </div>
            <details open={initial ? true : undefined}>
              <summary>Дополнительные данные</summary>
              <div className="rag-fields">
                <label>Описание<textarea name="description" defaultValue={initial?.description ?? ""} rows={2} /></label>
                <label>Шаги (каждый с новой строки)<textarea name="steps" defaultValue={initial?.steps.join("\n")} rows={4} /></label>
                <p className="muted small">КБЖУ на 100 г. Пустое поле означает «нет данных».</p>
                <div className="rag-nutrition">{nutritionFields.map(([key, label]) => <label key={key}>{label}<input name={key} defaultValue={initial?.nutrition_per_100g[key] ?? ""} type="number" min="0" step="any" /></label>)}</div>
                <label>Общее время, мин<input name="time" defaultValue={initial?.total_time_minutes ?? ""} type="number" min="1" step="1" /></label>
              </div>
            </details>
            <button className="button primary" type="submit">{saving ? "Сохраняем…" : initial ? "Сохранить изменения" : "Добавить рецепт"}</button>
            {initial && <button type="button" className="button secondary" onClick={onCancel}>Отменить редактирование</button>}
          </fieldset>
          {formError && <p className="field-error" role="alert">{formError}</p>}
          {!!error && <ErrorBox error={error} />}
        </form>
  );
}
