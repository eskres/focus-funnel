// /auth/login in demo mode: no login, straight back to the page. Design
// decision 14 relies on this step: after the API proxy marks a dead demo
// value, the page's redirect through here must reach a page path, where
// proxy.ts starts a new session.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_RETURN_TO } from "@/lib/login";

import { GET } from "./route";

const APP = "http://localhost:3000";

describe("/auth/login in demo mode", () => {
  beforeEach(() => {
    vi.stubEnv("AUTH_MODE", "demo");
    vi.stubEnv("SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    vi.stubEnv("BACKEND_URL", "http://backend:8000");
  });
  afterEach(() => vi.unstubAllEnvs());

  it("redirects straight back to returnTo without setting a cookie", async () => {
    const response = await GET(new Request(`${APP}/auth/login?returnTo=%2Fapp%3Fx%3D1`));
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(`${APP}/app?x=1`);
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it.each([
    "https://evil.example/app",
    "//evil.example/app",
    "/.//evil.example/app",
    "/x/..//evil.example/app",
    "/%2e//evil.example/app",
    "/./\\evil.example/app",
    null,
  ])(
    "redirects to the default page for an unsafe or missing returnTo (%s)",
    async (returnTo) => {
      const url = new URL("/auth/login", APP);
      if (returnTo !== null) url.searchParams.set("returnTo", returnTo);
      const response = await GET(new Request(url));
      expect(response.headers.get("location")).toBe(new URL(DEFAULT_RETURN_TO, APP).toString());
    },
  );
});
