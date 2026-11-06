import { afterEach, describe, expect, it, vi } from "vitest";

import { ValidationError } from "@/lib/api";
import { errorResponse, fakeApi, json } from "@/test/fake-api";

import { saveCap } from "./usage";

afterEach(() => {
  vi.unstubAllGlobals();
});

const state = { unit: "usd", amount: 5, reached: false, resets_on: "2026-12-01" };

describe("saveCap", () => {
  it("sends the cap to PUT /api/usage/cap and answers the saved state", async () => {
    const { calls } = fakeApi({ "PUT /api/usage/cap": json(200, { cap: state }) });

    await expect(saveCap({ unit: "usd", amount: 5 })).resolves.toEqual(state);

    expect(calls).toEqual([
      { method: "PUT", path: "/api/usage/cap", body: { cap: { unit: "usd", amount: 5 } } },
    ]);
  });

  it("sends null to remove the cap", async () => {
    const { calls } = fakeApi({ "PUT /api/usage/cap": json(200, { cap: null }) });

    await expect(saveCap(null)).resolves.toBeNull();

    expect(calls[0]).toEqual({ method: "PUT", path: "/api/usage/cap", body: { cap: null } });
  });

  it("throws the backend's validation error", async () => {
    fakeApi({
      "PUT /api/usage/cap": errorResponse(422, "validation_error", "The amount must be above zero."),
    });

    const error = await saveCap({ unit: "tokens", amount: 0 }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ValidationError);
    expect(error).toMatchObject({ message: "The amount must be above zero.", status: 422 });
  });
});
