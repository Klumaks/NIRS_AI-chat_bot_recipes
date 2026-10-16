import { expect, it } from "vitest";
import { splitProducts } from "../lib/products";
it("splits product labels on comma and standalone conjunction while keeping compound names", () => {
  expect(splitProducts("  Курица, рис И лук ")).toEqual(["Курица", "рис", "лук"]);
  expect(splitProducts("индейка и оливковое масло, рисовая лапша")).toEqual(["индейка", "оливковое масло", "рисовая лапша"]);
  expect(splitProducts(", и , И ")).toEqual([]);
});
