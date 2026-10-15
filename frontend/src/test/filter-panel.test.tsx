import { it, expect, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterPanel } from "../components/FilterPanel";
it("does not submit an inverted range and reset emits empty filters", async () => {
  const apply = vi.fn();
  render(
    <FilterPanel
      filters={{}}
      onApply={apply}
      onClose={() => {}}
      pending={false}
    />,
  );
  const u = userEvent.setup();
  await u.type(screen.getByLabelText("Калории, ккал: от"), "200");
  await u.type(screen.getByLabelText("Калории, ккал: до"), "100");
  await u.click(screen.getByRole("button", { name: "Применить" }));
  expect(apply).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "минимум больше максимума",
  );
  await u.click(screen.getByRole("button", { name: "Сбросить" }));
  expect(apply).toHaveBeenCalledWith({});
  cleanup();
});
