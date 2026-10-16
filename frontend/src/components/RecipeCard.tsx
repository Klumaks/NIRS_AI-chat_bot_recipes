import { ArrowRight, Clock3 } from "lucide-react";
import type { Recipe } from "../api/types";
export function Nutrition({ recipe }: { recipe: Recipe }) {
  const n = recipe.nutrition_per_100g;
  const v = (x: number | null) => (x == null ? "нет данных" : x);
  return (
    <div className="nutrition">
      <strong>
        НА 100 Г · {n.kcal == null ? "нет данных" : n.kcal + " ккал"}
      </strong>
      <span>
        Б {v(n.protein_g)}
        {n.protein_g != null ? " г" : ""} · Ж {v(n.fat_g)}
        {n.fat_g != null ? " г" : ""} · У {v(n.carbs_g)}
        {n.carbs_g != null ? " г" : ""}
      </span>
    </div>
  );
}
export function RecipeCard({
  recipe,
  index,
  onSelect,
  disabled,
}: {
  recipe: Recipe;
  index: number;
  onSelect: () => void;
  disabled: boolean;
}) {
  return (
    <article className="recipe-card">
      <small className="recipe-kicker">
        {String(index + 1).padStart(2, "0")} / ИЗ ВАШИХ ПРОДУКТОВ
      </small>
      <h2>{recipe.title}</h2>
      <p className="recipe-description">
        {recipe.description || "Описание: нет данных"}
      </p>
      <div className="recipe-meta">
        <Clock3 size={15} />
        <span>
          {recipe.total_time_minutes == null
            ? "Время: нет данных"
            : recipe.total_time_minutes + " мин"}
        </span>
      </div>
      <Nutrition recipe={recipe} />
      <p className="missing">
        Не хватает:{" "}
        {recipe.missing_ingredients.length
          ? recipe.missing_ingredients.join(", ")
          : "все продукты есть"}
      </p>
      <a
        className="source-link"
        href={recipe.url}
        target="_blank"
        rel="noreferrer"
      >
        {recipe.data_mode === "demo"
          ? "Источник: демонстрационный пример"
          : "Источник рецепта"}
      </a>
      <button className="button primary" onClick={onSelect} disabled={disabled}>
        Открыть рецепт <ArrowRight size={17} />
      </button>
    </article>
  );
}
