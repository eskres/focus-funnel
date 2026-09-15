import { NextRequest, NextResponse } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { middleware, getSession } = vi.hoisted(() => ({
  middleware: vi.fn(),
  getSession: vi.fn(),
}));

vi.mock("@/lib/auth0", () => ({ auth0: { middleware, getSession } }));

import { proxy } from "./proxy";

const request = (path: string) => new NextRequest(`http://localhost:3000${path}`);

beforeEach(() => {
  vi.clearAllMocks();
  middleware.mockImplementation(async () => NextResponse.next());
  getSession.mockResolvedValue(null);
});

describe("auth proxy", () => {
  it("lets logged-out users open the landing page", async () => {
    const response = await proxy(request("/"));

    expect(response.headers.get("location")).toBeNull();
    expect(getSession).not.toHaveBeenCalled();
  });

  it("hands /auth/* routes to the Auth0 SDK", async () => {
    const sdkResponse = NextResponse.redirect("https://tenant.example/authorize");
    middleware.mockResolvedValue(sdkResponse);

    const response = await proxy(request("/auth/login"));

    expect(response).toBe(sdkResponse);
  });

  it.each(["/app", "/settings"])(
    "redirects logged-out users from %s to login with a return path",
    async (path) => {
      const response = await proxy(request(`${path}?tab=1`));

      const location = new URL(response.headers.get("location")!);
      expect(location.pathname).toBe("/auth/login");
      expect(location.searchParams.get("returnTo")).toBe(`${path}?tab=1`);
    },
  );

  it("lets logged-in users through", async () => {
    getSession.mockResolvedValue({ user: { sub: "auth0|user-1" } });

    const response = await proxy(request("/app"));

    expect(response.headers.get("location")).toBeNull();
  });

  it("leaves logged-out API calls to the route handler's 401", async () => {
    const response = await proxy(request("/api/me"));

    expect(response.headers.get("location")).toBeNull();
    expect(getSession).not.toHaveBeenCalled();
  });
});
