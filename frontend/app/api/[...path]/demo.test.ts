// The API proxy in demo mode: held keys, the end of a session, and no-store.
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readAuthConfig } from "@/lib/auth-mode";
import { heldKeysCookie, readHeldKeys, type HeldKeys } from "@/lib/demo-keys";
import { DEMO_KEYS_COOKIE, DEMO_SESSION_COOKIE } from "@/lib/session";

import { DELETE, GET, PUT } from "./route";

const SECRET = "0123456789abcdef0123456789abcdef";
const KEY = "nb-demo-secret-key-9876";
const APP = "http://localhost:3000";
const MINUTE = 60_000;

type Handler = (req: IncomingMessage, body: string, res: ServerResponse) => void;
interface Backend {
  url: string;
  requests: { method?: string; url?: string; headers: IncomingMessage["headers"]; body: string }[];
  close: () => Promise<void>;
}

async function startBackend(handler: Handler): Promise<Backend> {
  const requests: Backend["requests"] = [];
  const server: Server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => {
      const body = Buffer.concat(chunks).toString();
      requests.push({ method: req.method, url: req.url, headers: req.headers, body });
      handler(req, body, res);
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    requests,
    close: () => {
      server.closeAllConnections();
      return new Promise((resolve) => server.close(() => resolve()));
    },
  };
}

const json = (status: number, body: unknown): Handler => (_req, _body, res) => {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
};
const heldStatus = { id: "nebius", key_saved: true, key_held: true, key_last4: "9876" };
const ctx = (...path: string[]) => ({ params: Promise.resolve({ path }) });

let backend: Backend;

function useDemo(backendUrl: string) {
  for (const [name, value] of Object.entries({
    AUTH_MODE: "demo",
    SESSION_SECRET: SECRET,
    BACKEND_URL: backendUrl,
  })) {
    vi.stubEnv(name, value);
  }
}

const demo = () => readAuthConfig({ AUTH_MODE: "demo", SESSION_SECRET: SECRET }).demo!;

async function keysCookie(held: HeldKeys): Promise<string> {
  return (await heldKeysCookie(held, SECRET, demo())).split(";")[0];
}

function visitor(url: string, init: RequestInit = {}, extraCookie = "") {
  const headers = new Headers(init.headers);
  headers.set("cookie", [`${DEMO_SESSION_COOKIE}=visitor-session`, extraCookie].filter(Boolean).join("; "));
  return new Request(url, { ...init, headers });
}

const sentKeys = (index = 0) => {
  const header = backend.requests[index].headers["x-provider-keys"];
  return header ? JSON.parse(Buffer.from(String(header), "base64url").toString()) : null;
};

const cookieHeader = (response: Response) =>
  response.headers.getSetCookie().map((h) => h.split(";")[0]).join("; ");

afterEach(async () => {
  await backend?.close();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("held keys in demo mode", () => {
  beforeEach(async () => {
    backend = await startBackend(json(200, heldStatus));
    useDemo(backend.url);
  });

  it("adds the key to a sealed cookie after a successful save", async () => {
    const response = await PUT(
      visitor(`${APP}/api/providers/nebius/key`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: KEY }),
      }),
      ctx("providers", "nebius", "key"),
    );

    expect(response.status).toBe(200);
    // The backend checked the key; its answer has no key and gains the expiry.
    expect(JSON.parse(backend.requests[0].body)).toEqual({ key: KEY });
    const body = await response.json();
    expect(body).toMatchObject({ key_held: true, key_last4: "9876" });
    expect(Date.parse(body.key_expires_at)).toBeGreaterThan(Date.now() + 29 * MINUTE);
    expect(JSON.stringify(body)).not.toContain(KEY);

    const [cookie] = response.headers.getSetCookie();
    expect(cookie).toMatch(new RegExp(`^${DEMO_KEYS_COOKIE}=.*HttpOnly; Secure; SameSite=Lax`));
    expect(cookie).not.toContain(KEY);
    const held = await readHeldKeys(new Request(APP, { headers: { cookie: cookieHeader(response) } }), SECRET);
    expect(held?.keys.nebius.key).toBe(KEY);
  });

  it("does not hold a key the provider refused", async () => {
    await backend.close();
    backend = await startBackend(json(400, { error: { code: "provider_key_invalid", message: "no" } }));
    useDemo(backend.url);

    const response = await PUT(
      visitor(`${APP}/api/providers/nebius/key`, { method: "PUT", body: JSON.stringify({ key: KEY }) }),
      ctx("providers", "nebius", "key"),
    );

    expect(response.status).toBe(400);
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("sends held keys to the backend and refreshes their last use", async () => {
    const now = Date.now();
    const cookie = await keysCookie({ keys: { nebius: { key: KEY, set_at: now - 10 * MINUTE } }, last_used_at: now - 5 * MINUTE });

    const response = await GET(visitor(`${APP}/api/providers`, {}, cookie), ctx("providers"));

    expect(response.status).toBe(200);
    const sent = sentKeys();
    expect(sent.nebius.key).toBe(KEY);
    expect(Date.parse(sent.nebius.expires_at)).toBeGreaterThan(Date.now() + 29 * MINUTE);
    const held = await readHeldKeys(new Request(APP, { headers: { cookie: cookieHeader(response) } }), SECRET);
    expect(held!.last_used_at).toBeGreaterThanOrEqual(now);
  });

  it("drops every key after the idle time", async () => {
    const now = Date.now();
    const cookie = await keysCookie({
      keys: { nebius: { key: KEY, set_at: now - 40 * MINUTE } },
      last_used_at: now - 31 * MINUTE,
    });

    const response = await GET(visitor(`${APP}/api/providers`, {}, cookie), ctx("providers"));

    expect(backend.requests[0].headers["x-provider-keys"]).toBeUndefined();
    expect(response.headers.getSetCookie()).toEqual([expect.stringMatching(new RegExp(`^${DEMO_KEYS_COOKIE}=;.*Max-Age=0`))]);
  });

  it("drops a key past its maximum age even while the visitor is active", async () => {
    const now = Date.now();
    const cookie = await keysCookie({
      keys: {
        nebius: { key: KEY, set_at: now - 4 * 60 * MINUTE - MINUTE },
        openrouter: { key: "or-other-key-1111", set_at: now - MINUTE },
      },
      last_used_at: now - MINUTE,
    });

    await GET(visitor(`${APP}/api/providers`, {}, cookie), ctx("providers"));

    expect(Object.keys(sentKeys())).toEqual(["openrouter"]);
  });

  it("forgets one key on DELETE without calling the backend", async () => {
    const now = Date.now();
    const cookie = await keysCookie({
      keys: { nebius: { key: KEY, set_at: now }, openrouter: { key: "or-other-key-1111", set_at: now } },
      last_used_at: now,
    });

    const response = await DELETE(
      visitor(`${APP}/api/providers/nebius/key`, { method: "DELETE" }, cookie),
      ctx("providers", "nebius", "key"),
    );

    expect(response.status).toBe(204);
    expect(backend.requests).toHaveLength(0);
    const held = await readHeldKeys(new Request(APP, { headers: { cookie: cookieHeader(response) } }), SECRET);
    expect(Object.keys(held!.keys)).toEqual(["openrouter"]);
  });

  it("never puts a key in a response body or a readable cookie", async () => {
    const now = Date.now();
    const cookie = await keysCookie({ keys: { nebius: { key: KEY, set_at: now } }, last_used_at: now });

    const responses = [
      await GET(visitor(`${APP}/api/providers`, {}, cookie), ctx("providers")),
      await PUT(
        visitor(`${APP}/api/providers/nebius/key`, { method: "PUT", body: JSON.stringify({ key: KEY }) }, cookie),
        ctx("providers", "nebius", "key"),
      ),
      await DELETE(
        visitor(`${APP}/api/providers/nebius/key`, { method: "DELETE" }, cookie),
        ctx("providers", "nebius", "key"),
      ),
    ];
    for (const response of responses) {
      expect(await response.text()).not.toContain(KEY);
      for (const setCookie of response.headers.getSetCookie()) {
        expect(setCookie).not.toContain(KEY);
        expect(setCookie).toContain("HttpOnly");
      }
    }
  });

  it("marks every response no-store", async () => {
    const response = await GET(visitor(`${APP}/api/me`), ctx("me"));
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("sends the demo session value as the credential and answers 401 without one", async () => {
    await GET(visitor(`${APP}/api/me`), ctx("me"));
    expect(backend.requests[0].headers.authorization).toBe("Bearer visitor-session");

    const response = await GET(new Request(`${APP}/api/me`), ctx("me"));
    expect(response.status).toBe(401);
    expect(backend.requests).toHaveLength(1);
  });
});

describe("the end of a demo session", () => {
  it("clears the demo cookies when the backend says the session expired", async () => {
    backend = await startBackend(
      json(401, { error: { code: "demo_session_expired", message: "Your demo session has ended." } }),
    );
    useDemo(backend.url);

    const response = await GET(visitor(`${APP}/api/me`), ctx("me"));

    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ error: { code: "demo_session_expired" } });
    const cleared = response.headers.getSetCookie();
    expect(cleared).toEqual(
      expect.arrayContaining([
        expect.stringMatching(new RegExp(`^${DEMO_SESSION_COOKIE}=;.*Max-Age=0`)),
        expect.stringMatching(new RegExp(`^${DEMO_KEYS_COOKIE}=;.*Max-Age=0`)),
      ]),
    );
  });

  it("clears the demo cookies after End demo", async () => {
    backend = await startBackend((_req, _body, res) => {
      res.writeHead(204);
      res.end();
    });
    useDemo(backend.url);

    const response = await DELETE(visitor(`${APP}/api/demo/session`, { method: "DELETE" }), ctx("demo", "session"));

    expect(response.status).toBe(204);
    expect(backend.requests[0].method).toBe("DELETE");
    expect(response.headers.getSetCookie().join()).toContain(`${DEMO_SESSION_COOKIE}=;`);
  });
});
