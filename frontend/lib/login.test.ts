import { describe, expect, it } from "vitest";

import { DEFAULT_RETURN_TO, safeReturnTo } from "./login";

describe("safeReturnTo (thought-export task 4.3)", () => {
  it.each([
    "/api/me/export?format=json",
    "/api/me/%65xport?format=json",
    "/%61pi/me/export?format=json",
    "/auth/logout",
    "/api",
    "/settings/../api/me/export?format=json",
    "/settings/%2e%2e/api/me/export?format=json",
    "/settings/%2e%2e/api/me/export",
    "/./api/me/export",
    "/./api/me/export?format=json",
    "/%2e/api/me/export?format=json",
    "/a\tpi/me/export?format=json",
    "/\t/evil.example",
    "/\n/evil.example",
  ])("sends %j to /app: it resolves to an API or auth route or another site", (value) => {
    expect(safeReturnTo(value)).toBe("/app");
  });

  it.each(["/settings", "/settings?tab=x", "/settings?tab=x#h", "/app"])(
    "returns the page %j unchanged",
    (value) => {
      expect(safeReturnTo(value)).toBe(value);
    },
  );

  it("returns the resolved path, not the raw value", () => {
    expect(safeReturnTo("/settings/../settings")).toBe("/settings");
  });

  it.each(["//evil.example", "/\\evil.example", "https://evil.example", "", null, undefined])(
    "still sends %j to /app",
    (value) => {
      expect(safeReturnTo(value)).toBe(DEFAULT_RETURN_TO);
      expect(DEFAULT_RETURN_TO).toBe("/app");
    },
  );

  it("sends a first segment that does not percent-decode to /app", () => {
    expect(safeReturnTo("/%E0%A4%A/settings")).toBe("/app");
  });
});
