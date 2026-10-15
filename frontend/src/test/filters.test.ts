import { describe, it, expect } from "vitest";
import { matchesFilters, validateFilters } from "../lib/filters";
import { recipes } from "../mocks/fixtures";
describe("Filter semantics", () => {
  it("includes boundaries and composes nutrition and duration", () => {
    expect(
      matchesFilters(recipes[0], {
        kcal: { min: 165, max: 165 },
        protein_g: { min: 12 },
        max_total_time_minutes: 25,
      }),
    ).toBe(true);
    expect(
      matchesFilters(recipes[0], {
        kcal: { max: 165 },
        max_total_time_minutes: 24,
      }),
    ).toBe(false);
  });
  it("unknown is not zero, but is allowed without a filter", () => {
    expect(matchesFilters(recipes[4], {})).toBe(true);
    expect(matchesFilters(recipes[4], { kcal: { min: 0 } })).toBe(false);
    expect(matchesFilters(recipes[4], { max_total_time_minutes: 60 })).toBe(
      false,
    );
  });
  it("rejects negative, inverted, non-finite and fractional time", () => {
    for (const f of [
      { kcal: { min: -1 } },
      { kcal: { min: 2, max: 1 } },
      { kcal: { max: Infinity } },
      { max_total_time_minutes: 2.5 },
    ])
      expect(validateFilters(f)).not.toBeNull();
  });
});
