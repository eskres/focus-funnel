import { describe, expect, it } from "vitest";

import { categoryChoices, hasEmptyField, parseTags } from "./thought-fields";

describe("thought fields", () => {
  it("splits tags on commas and drops empty ones", () => {
    expect(parseTags(" groceries,, milk ,")).toEqual(["groceries", "milk"]);
  });

  it("offers the user's categories, then each kept one they removed, once", () => {
    expect(categoryChoices(["task", "idea"], "trip", null, "trip", "", "task")).toEqual(["task", "idea", "trip"]);
    expect(categoryChoices(["task"])).toEqual(["task"]);
  });

  it("finds an empty title or summary, spaces included", () => {
    const text = { title: "Oat milk", summary: "Buy it.", tags: "", category: "" };
    expect(hasEmptyField(text)).toBe(false);
    expect(hasEmptyField({ ...text, title: "  " })).toBe(true);
    expect(hasEmptyField({ ...text, summary: "" })).toBe(true);
  });
});
