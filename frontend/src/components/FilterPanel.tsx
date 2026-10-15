import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { X } from "lucide-react";
import type { Filters } from "../api/types";
import { nutritionFields, validateFilters } from "../lib/filters";
type Values = Record<string, string>;
function defaults(f: Filters): Values {
  const v: Values = { time: f.max_total_time_minutes?.toString() || "" };
  for (const [key] of nutritionFields) {
    v[key + "_min"] = f[key]?.min?.toString() || "";
    v[key + "_max"] = f[key]?.max?.toString() || "";
  }
  return v;
}
export function FilterPanel({
  filters,
  onApply,
  onClose,
  pending,
}: {
  filters: Filters;
  onApply: (f: Filters) => void;
  onClose: () => void;
  pending: boolean;
}) {
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<Values>({ defaultValues: defaults(filters) });
  useEffect(() => reset(defaults(filters)), [filters, reset]);
  function submit(v: Values) {
    const f: Filters = {};
    for (const [key] of nutritionFields) {
      const min = v[key + "_min"];
      const max = v[key + "_max"];
      if (min !== "" || max !== "")
        f[key] = {
          min: min === "" ? null : Number(min),
          max: max === "" ? null : Number(max),
        };
    }
    if (v.time !== "") f.max_total_time_minutes = Number(v.time);
    const e = validateFilters(f);
    if (e) {
      setError("root", { message: e });
      return;
    }
    onApply(f);
  }
  return (
    <aside className="filter-panel" aria-label="Фильтры">
      <div className="filter-heading">
        <h2>Фильтры</h2>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Закрыть фильтры"
        >
          <X size={19} />
        </button>
      </div>
      <p className="muted small">КБЖУ на 100 г готового блюда</p>
      <form onSubmit={handleSubmit(submit)} noValidate>
        {nutritionFields.map(([key, label]) => (
          <fieldset key={key}>
            <legend>{label}</legend>
            <div className="range-fields">
              <label className="sr-only" htmlFor={key + "-min"}>
                {label}: от
              </label>
              <input
                id={key + "-min"}
                type="number"
                min="0"
                step="any"
                placeholder="От"
                {...register(key + "_min")}
              />
              <label className="sr-only" htmlFor={key + "-max"}>
                {label}: до
              </label>
              <input
                id={key + "-max"}
                type="number"
                min="0"
                step="any"
                placeholder="До"
                {...register(key + "_max")}
              />
            </div>
          </fieldset>
        ))}
        <label>
          Общее время, мин
          <input
            type="number"
            min="1"
            step="1"
            placeholder="Не более"
            {...register("time")}
          />
        </label>
        {errors.root && (
          <p className="field-error" role="alert">
            {errors.root.message}
          </p>
        )}
        <button className="button primary full" disabled={pending}>
          Применить
        </button>
        <button
          type="button"
          className="text-button centered"
          disabled={pending}
          onClick={() => {
            reset(defaults({}));
            onApply({});
          }}
        >
          Сбросить
        </button>
        <p className="muted small">
          Если значение неизвестно, блюдо не попадёт под активный фильтр.
        </p>
      </form>
    </aside>
  );
}
