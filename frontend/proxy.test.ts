import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEMO_SESSION_COOKIE, sessionCookies, type Session } from "@/lib/session";

import { proxy, resetDemoLimits } from "./proxy";

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

const request = (path: string, cookie?: string, headers: Record<string, string> = {}) =>
  new NextRequest(`http://localhost:3000${path}`, {
    headers: { ...(cookie ? { cookie } : {}), ...headers },
  });

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
    resetDemoLimits();
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

describe("demo mode guards", () => {
  const backend = vi.fn();
  const withSession = `${DEMO_SESSION_COOKIE}=existing`;

  beforeEach(() => {
    useMode("demo");
    resetDemoLimits();
    backend.mockReset();
    backend.mockImplementation(async () =>
      Response.json(
        { session: "value", expires_at: new Date(Date.now() + 3600_000).toISOString() },
        { status: 201 },
      ),
    );
    vi.stubGlobal("fetch", backend);
  });

  it("marks every response no-store", async () => {
    vi.stubEnv("DEMO_RATE_LIMIT", "2");
    const responses = [
      await proxy(request("/app", withSession)),
      await proxy(request("/", withSession)),
      await proxy(request("/app")),
      await proxy(request("/api/me", withSession)),
      await proxy(request("/demo/ended")),
    ];
    for (const response of responses) expect(response.headers.get("cache-control")).toBe("no-store");
    // Also the refusals.
    expect(responses[2].status).toBe(429);
    expect(responses[2].headers.get("cache-control")).toBe("no-store");
  });

  it("answers requests past DEMO_RATE_LIMIT with 429 rate_limited and Retry-After", async () => {
    vi.stubEnv("DEMO_RATE_LIMIT", "3");
    for (let i = 0; i < 3; i++) {
      expect((await proxy(request("/api/me", withSession))).status).not.toBe(429);
    }

    const refused = await proxy(request("/api/me", withSession));

    expect(refused.status).toBe(429);
    expect(await refused.json()).toMatchObject({ error: { code: "rate_limited" } });
    const retryAfter = Number(refused.headers.get("retry-after"));
    expect(retryAfter).toBeGreaterThanOrEqual(1);
    expect(retryAfter).toBeLessThanOrEqual(20);

    const page = await proxy(request("/app", withSession));
    expect(page.status).toBe(429);
    expect(page.headers.get("retry-after")).toBeTruthy();
  });

  it("refuses session starts past the hourly limit without calling the backend", async () => {
    vi.stubEnv("DEMO_NEW_SESSIONS_PER_HOUR", "2");
    await proxy(request("/app"));
    await proxy(request("/app"));
    expect(backend).toHaveBeenCalledTimes(2);

    const refused = await proxy(request("/app"));

    expect(backend).toHaveBeenCalledTimes(2);
    expect(refused.headers.get("x-middleware-rewrite")).toContain("/demo/unavailable?reason=limit");
    expect(refused.headers.get("retry-after")).toBeTruthy();
    expect(refused.headers.getSetCookie()).toEqual([]);
    // A visitor who already has a session is not affected.
    expect((await proxy(request("/app", withSession))).headers.get("x-middleware-rewrite")).toBeNull();
  });

  it("ignores X-Forwarded-For without TRUSTED_PROXY: every request shares one limit", async () => {
    vi.stubEnv("DEMO_RATE_LIMIT", "2");
    const from = (address: string) =>
      proxy(request("/api/me", withSession, { "x-forwarded-for": address }));

    expect((await from("198.51.100.1")).status).not.toBe(429);
    expect((await from("198.51.100.2")).status).not.toBe(429);
    expect((await from("198.51.100.3")).status).toBe(429);
  });

  it("uses the last X-Forwarded-For hop with TRUSTED_PROXY=true", async () => {
    vi.stubEnv("DEMO_RATE_LIMIT", "2");
    vi.stubEnv("TRUSTED_PROXY", "true");
    const from = (header: string) =>
      proxy(request("/api/me", withSession, { "x-forwarded-for": header }));

    expect((await from("203.0.113.9")).status).not.toBe(429);
    expect((await from("203.0.113.9")).status).not.toBe(429);
    expect((await from("203.0.113.9")).status).toBe(429);
    // A spoofed first hop does not help: the proxy's hop is last.
    expect((await from("10.0.0.1, 203.0.113.9")).status).toBe(429);
    // Another client has its own limit.
    expect((await from("10.0.0.1, 203.0.113.10")).status).not.toBe(429);
  });
});
