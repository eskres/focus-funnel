import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEMO_SESSION_COOKIE, sessionCookies, type Session } from "@/lib/session";

import { proxy } from "./proxy";

const SECRET = "0123456789abcdef0123456789abcdef";
const BASE = { SESSION_SECRET: SECRET, APP_BASE_URL: "http://localhost:3000" };
const MODES = {
  oidc: {
    AUTH_MODE: "oidc",
    OIDC_ISSUER: "http://localhost:1411",
    OIDC_CLIENT_ID: "client-id",
    OIDC_CLIENT_SECRET: "client-secret",
  },
  firebase: {
    AUTH_MODE: "firebase",
    FIREBASE_PROJECT_ID: "focus-funnel",
    FIREBASE_API_KEY: "web-api-key",
    FIREBASE_AUTH_DOMAIN: "focus-funnel.firebaseapp.com",
  },
  demo: { AUTH_MODE: "demo", BACKEND_URL: "http://backend:8000" },
};

function useMode(mode: keyof typeof MODES) {
  for (const [name, value] of Object.entries({ ...BASE, ...MODES[mode] })) vi.stubEnv(name, value);
}

async function sessionCookie(mode: Session["mode"]): Promise<string> {
  const session: Session = {
    mode,
    idToken: "id-token",
    refreshToken: "refresh",
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
  };
  const headers = await sessionCookies(new Request("http://localhost:3000/"), session, SECRET);
  return headers.map((header) => header.split(";")[0]).join("; ");
}

const request = (path: string, cookie?: string) =>
  new NextRequest(`http://localhost:3000${path}`, cookie ? { headers: { cookie } } : undefined);

const location = (response: Response) => {
  const value = response.headers.get("location");
  return value ? new URL(value) : null;
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe.each(["oidc", "firebase"] as const)("proxy in %s mode", (mode) => {
  beforeEach(() => useMode(mode));

  it("lets logged-out users open the landing page", async () => {
    expect(location(await proxy(request("/")))).toBeNull();
  });

  it("sends logged-in users from the landing page to the app", async () => {
    const response = await proxy(request("/", await sessionCookie(mode)));
    expect(location(response)?.pathname).toBe("/app");
  });

  it("lets logged-in users through", async () => {
    const response = await proxy(request("/app", await sessionCookie(mode)));
    expect(location(response)).toBeNull();
  });

  it("treats a session from another mode as logged out", async () => {
    const other = mode === "oidc" ? "firebase" : "oidc";
    const response = await proxy(request("/app", await sessionCookie(other)));
    expect(location(response)).not.toBeNull();
  });

  it.each(["/auth/login", "/auth/callback?code=x", "/api/me"])("leaves %s to its route", async (path) => {
    expect(location(await proxy(request(path)))).toBeNull();
  });
});

describe("login redirects", () => {
  it.each(["/app", "/settings"])(
    "sends a logged-out user on %s to /auth/login with returnTo in oidc mode",
    async (path) => {
      useMode("oidc");
      const url = location(await proxy(request(`${path}?tab=1`)));
      expect(url?.pathname).toBe("/auth/login");
      expect(url?.searchParams.get("returnTo")).toBe(`${path}?tab=1`);
    },
  );

  it("sends a logged-out user on /app to /login with returnTo in firebase mode", async () => {
    useMode("firebase");
    const url = location(await proxy(request("/app/abc")));
    expect(url?.pathname).toBe("/login");
    expect(url?.searchParams.get("returnTo")).toBe("/app/abc");
  });

  it("lets a logged-out user open /login in firebase mode", async () => {
    useMode("firebase");
    expect(location(await proxy(request("/login")))).toBeNull();
  });

  it("answers 500 when the auth settings are not valid", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubEnv("AUTH_MODE", "");
    const response = await proxy(request("/app"));
    expect(response.status).toBe(500);
  });
});

describe("proxy in demo mode", () => {
  const backend = vi.fn();

  beforeEach(() => {
    useMode("demo");
    backend.mockReset();
    vi.stubGlobal("fetch", backend);
  });

  const started = (session = "demo-session-value") =>
    backend.mockResolvedValue(
      Response.json(
        { session, expires_at: new Date(Date.now() + 24 * 3600 * 1000).toISOString() },
        { status: 201 },
      ),
    );

  it("starts a session instead of sending the visitor to a login", async () => {
    started();

    const response = await proxy(request("/app"));

    expect(location(response)).toBeNull();
    expect(backend).toHaveBeenCalledWith(
      new URL("/api/demo/sessions", "http://backend:8000"),
      expect.objectContaining({ method: "POST" }),
    );
    const [cookie] = response.headers.getSetCookie();
    expect(cookie).toMatch(new RegExp(`^${DEMO_SESSION_COOKIE}=demo-session-value;`));
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("Secure");
    expect(cookie).toContain("SameSite=Lax");
    const maxAge = Number(/Max-Age=(\d+)/.exec(cookie)?.[1]);
    expect(maxAge).toBeGreaterThan(24 * 3600 - 60);
    expect(maxAge).toBeLessThanOrEqual(24 * 3600);
  });

  it("starts a session on the landing page and goes to the app", async () => {
    started();
    const response = await proxy(request("/"));
    expect(location(response)?.pathname).toBe("/app");
    expect(response.headers.getSetCookie()[0]).toContain(`${DEMO_SESSION_COOKIE}=`);
  });

  it("keeps an existing session", async () => {
    const response = await proxy(request("/app", `${DEMO_SESSION_COOKIE}=existing`));
    expect(location(response)).toBeNull();
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(backend).not.toHaveBeenCalled();
  });

  it("shows that the demo is full", async () => {
    backend.mockResolvedValue(
      Response.json({ error: { code: "demo_full", message: "full" } }, { status: 503 }),
    );
    const response = await proxy(request("/app"));
    expect(response.headers.get("x-middleware-rewrite")).toContain("/demo/unavailable?reason=full");
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("does not start a session for API calls", async () => {
    await proxy(request("/api/me"));
    expect(backend).not.toHaveBeenCalled();
  });
});
