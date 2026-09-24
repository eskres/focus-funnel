import {
  createServer,
  type IncomingMessage,
  type Server,
  type ServerResponse,
} from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { refreshOidcSession } = vi.hoisted(() => ({ refreshOidcSession: vi.fn() }));

vi.mock("@/lib/oidc", () => ({ refreshOidcSession }));

import { resetRenewals } from "@/lib/auth-mode";
import { SESSION_COOKIE, sessionCookies, type Session } from "@/lib/session";

import { DELETE, GET, POST, PUT } from "./route";

const SECRET = "0123456789abcdef0123456789abcdef";
const OIDC_ENV = {
  AUTH_MODE: "oidc",
  SESSION_SECRET: SECRET,
  APP_BASE_URL: "http://localhost:3000",
  OIDC_ISSUER: "http://localhost:1411",
  OIDC_CLIENT_ID: "client-id",
  OIDC_CLIENT_SECRET: "client-secret",
};

const inSeconds = (seconds: number) => Math.floor(Date.now() / 1000) + seconds;

const oidcSession = (overrides: Partial<Session> = {}): Session => ({
  mode: "oidc",
  idToken: "test-access-token",
  refreshToken: "test-refresh-token",
  expiresAt: inSeconds(3600),
  ...overrides,
});

/** The Cookie header a browser sends for a session. */
async function cookieFor(session: Session): Promise<string> {
  const headers = await sessionCookies(authed("http://localhost:3000/"), session, SECRET);
  return headers.map((header) => header.split(";")[0]).join("; ");
}

let sessionCookie = "";

/** A request from a logged-in browser: it carries the session cookie. */
function authed(url: string, init: RequestInit = {}): Request {
  const headers = new Headers(init.headers);
  const existing = headers.get("cookie");
  headers.set("cookie", existing ? `${existing}; ${sessionCookie}` : sessionCookie);
  return new Request(url, { ...init, headers });
}

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

const okBackend: Handler = (_req, _body, res) => {
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end("{}");
};

/** Route context as Next.js passes it for /api/[...path]. */
const ctx = (...path: string[]) => ({ params: Promise.resolve({ path }) });

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

let backend: Backend | undefined;

beforeEach(async () => {
  for (const [name, value] of Object.entries(OIDC_ENV)) vi.stubEnv(name, value);
  sessionCookie = await cookieFor(oidcSession());
  resetRenewals();
});

afterEach(async () => {
  await backend?.close();
  backend = undefined;
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("API proxy", () => {
  it("forwards method, path, query, body, and the access token", async () => {
    backend = await startBackend((_req, _body, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ saved: true, last4: "abcd" }));
    });
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await PUT(
      authed("http://localhost:3000/api/providers/nebius/key?x=1&y=two", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Cookie: "other=browser-cookie",
          Authorization: "Bearer client-supplied",
        },
        body: JSON.stringify({ api_key: "example-key-abcd" }),
      }),
      ctx("providers", "nebius", "key"),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ saved: true, last4: "abcd" });
    expect(response.headers.get("Cache-Control")).toBe("no-cache");
    expect(response.headers.get("X-Accel-Buffering")).toBe("no");

    expect(backend.requests).toHaveLength(1);
    const [forwarded] = backend.requests;
    expect(forwarded.method).toBe("PUT");
    expect(forwarded.url).toBe("/api/providers/nebius/key?x=1&y=two");
    expect(forwarded.body).toBe(JSON.stringify({ api_key: "example-key-abcd" }));
    expect(forwarded.headers.authorization).toBe("Bearer test-access-token");
    expect(forwarded.headers["content-type"]).toBe("application/json");
    expect(forwarded.headers.cookie).toBeUndefined();
  });

  it("passes backend status codes and empty bodies through", async () => {
    backend = await startBackend((_req, _body, res) => {
      res.writeHead(204);
      res.end();
    });
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await DELETE(
      authed("http://localhost:3000/api/providers/nebius/key", { method: "DELETE" }),
      ctx("providers", "nebius", "key"),
    );

    expect(response.status).toBe(204);
    expect(await response.text()).toBe("");
    expect(backend.requests[0].method).toBe("DELETE");
  });

  it("passes only allowlisted backend response headers", async () => {
    backend = await startBackend((_req, _body, res) => {
      res.writeHead(200, {
        "Content-Type": "application/json",
        "Content-Disposition": 'attachment; filename="thoughts.json"',
        "Set-Cookie": "backend=secret; HttpOnly",
        "WWW-Authenticate": 'Bearer realm="api"',
        Server: "uvicorn",
        Connection: "keep-alive",
        "Keep-Alive": "timeout=5",
        "Cache-Control": "max-age=3600",
      });
      res.end("{}");
    });
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(authed("http://localhost:3000/api/me"), ctx("me"));

    expect(response.headers.get("content-type")).toBe("application/json");
    expect(response.headers.get("content-disposition")).toBe(
      'attachment; filename="thoughts.json"',
    );
    expect(response.headers.get("cache-control")).toBe("no-cache");
    for (const name of ["set-cookie", "www-authenticate", "server", "connection", "keep-alive"]) {
      expect(response.headers.get(name)).toBeNull();
    }
  });

  it.each([
    ["dot-dot segment", ["..", "health"]],
    ["encoded dot-dot segment", ["%2e%2e", "health"]],
    ["mixed dot-dot segment", [".%2e", "health"]],
    ["dot segment", [".", "me"]],
    ["empty segment", ["", "me"]],
    ["other host", [".%2e", "", "127.0.0.1:9999", "steal"]],
    ["slash in segment", ["a/b"]],
    ["encoded slash in segment", ["..%2F..%2Fhealth"]],
    ["backslash in segment", ["a\\b"]],
    ["encoded backslash in segment", ["a%5Cb"]],
  ])("rejects a %s with 404 and no backend call", async (_name, segments) => {
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(authed("http://localhost:3000/api/x"), ctx(...segments));

    expect(response.status).toBe(404);
    expect(await response.json()).toMatchObject({
      error: { code: "not_found", message: expect.any(String) },
    });
    expect(backend.requests).toHaveLength(0);
    expect(refreshOidcSession).not.toHaveBeenCalled();
  });

  it("encodes segments so they stay inside /api/ on the backend host", async () => {
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(
      authed("http://localhost:3000/api/x"),
      ctx("thoughts", "a b?c#d:e"),
    );

    expect(response.status).toBe(200);
    expect(backend.requests[0].url).toBe("/api/thoughts/a%20b%3Fc%23d%3Ae");
  });

  // Next.js has already decoded the segment, so these cannot be decoded again.
  // They are literal strings, not traversal attempts, and are forwarded encoded.
  it.each([
    ["a literal percent sign", "100%", "/api/thoughts/100%25"],
    ["an incomplete escape", "%E0%A4%A", "/api/thoughts/%25E0%25A4%25A"],
  ])("forwards a segment with %s", async (_name, segment, expectedUrl) => {
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(
      authed("http://localhost:3000/api/x"),
      ctx("thoughts", segment),
    );

    expect(response.status).toBe(200);
    expect(backend.requests[0].url).toBe(expectedUrl);
  });

  it("turns a backend redirect into 502 backend_unreachable", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    backend = await startBackend((_req, _body, res) => {
      res.writeHead(302, { Location: "https://redirect-target.example/steal" });
      res.end();
    });
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(authed("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({
      error: { code: "backend_unreachable", message: expect.any(String) },
    });
    // The browser never sees a redirect it cannot follow.
    expect(response.headers.get("location")).toBeNull();
    expect(consoleError).toHaveBeenCalledWith(
      "API proxy: backend returned a redirect",
      expect.objectContaining({ method: "GET", path: "/api/me", status: 302 }),
    );
    const logged = JSON.stringify(consoleError.mock.calls);
    expect(logged).not.toContain("test-access-token");
    expect(logged).not.toContain("redirect-target.example");
  });

  it("returns 401 unauthenticated without calling the backend when there is no session", async () => {
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(new Request("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({
      error: { code: "unauthenticated", message: expect.any(String) },
    });
    expect(backend.requests).toHaveLength(0);
  });

  it("returns 401 for a session cookie sealed under another secret", async () => {
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);
    vi.stubEnv("SESSION_SECRET", "another-secret-that-is-long-enough-000");

    const response = await GET(authed("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(401);
    expect(backend.requests).toHaveLength(0);
  });

  it("forwards the ID token of a valid session without renewing it", async () => {
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(authed("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(200);
    expect(backend.requests[0].headers.authorization).toBe("Bearer test-access-token");
    expect(refreshOidcSession).not.toHaveBeenCalled();
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("renews a token that expires within 60 seconds before calling the backend", async () => {
    sessionCookie = await cookieFor(oidcSession({ idToken: "old-id-token", expiresAt: inSeconds(30) }));
    refreshOidcSession.mockResolvedValue(
      oidcSession({ idToken: "renewed-id-token", refreshToken: "rotated-refresh-token" }),
    );
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(authed("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(200);
    expect(refreshOidcSession).toHaveBeenCalledWith(
      expect.objectContaining({ issuer: "http://localhost:1411" }),
      "test-refresh-token",
    );
    expect(backend.requests[0].headers.authorization).toBe("Bearer renewed-id-token");
    const cookies = response.headers.getSetCookie();
    expect(cookies[0]).toMatch(new RegExp(`^${SESSION_COOKIE}=`));
    expect(cookies[0]).toContain("HttpOnly");
    // The browser never sees the tokens themselves.
    expect(cookies.join()).not.toContain("renewed-id-token");
    expect(cookies.join()).not.toContain("rotated-refresh-token");
  });

  it("shares one renewal between parallel calls", async () => {
    sessionCookie = await cookieFor(oidcSession({ expiresAt: inSeconds(10) }));
    refreshOidcSession.mockResolvedValue(oidcSession({ idToken: "renewed-id-token" }));
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    await Promise.all([
      GET(authed("http://localhost:3000/api/me"), ctx("me")),
      GET(authed("http://localhost:3000/api/me"), ctx("me")),
    ]);

    expect(refreshOidcSession).toHaveBeenCalledTimes(1);
    expect(backend.requests.map((r) => r.headers.authorization)).toEqual([
      "Bearer renewed-id-token",
      "Bearer renewed-id-token",
    ]);
  });

  it("clears the cookie and returns 401 without calling the backend when renewal fails", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    sessionCookie = await cookieFor(oidcSession({ expiresAt: inSeconds(-5) }));
    refreshOidcSession.mockRejectedValue(new Error("invalid_grant"));
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(authed("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ error: { code: "unauthenticated" } });
    expect(backend.requests).toHaveLength(0);
    const cookies = response.headers.getSetCookie();
    expect(cookies).toEqual([expect.stringMatching(new RegExp(`^${SESSION_COOKIE}=;.*Max-Age=0`))]);
  });

  it("ends a session without a refresh token when its ID token expires", async () => {
    sessionCookie = await cookieFor(oidcSession({ refreshToken: null, expiresAt: inSeconds(-5) }));
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(authed("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(401);
    expect(backend.requests).toHaveLength(0);
    expect(refreshOidcSession).not.toHaveBeenCalled();
  });

  it("returns 500 internal_error and logs when the auth settings are wrong", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubEnv("AUTH_MODE", "");
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(authed("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(500);
    expect(await response.json()).toMatchObject({ error: { code: "internal_error" } });
    expect(backend.requests).toHaveLength(0);
    expect(consoleError).toHaveBeenCalledWith(
      "API proxy: could not get a credential",
      expect.objectContaining({ message: expect.stringContaining("AUTH_MODE") }),
    );
  });

  it("returns 502 backend_unreachable and logs without the token", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    backend = await startBackend(okBackend);
    const closedUrl = backend.url;
    await backend.close();
    backend = undefined;
    vi.stubEnv("BACKEND_URL", closedUrl);

    const response = await GET(authed("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({ error: { code: "backend_unreachable" } });
    expect(consoleError).toHaveBeenCalledWith(
      "API proxy: backend request failed",
      expect.objectContaining({ method: "GET", path: "/api/me" }),
    );
    expect(JSON.stringify(consoleError.mock.calls)).not.toContain("test-access-token");
  });

  it("streams backend parts to the client one at a time", async () => {
    const parts = ["data: one\n\n", "data: two\n\n", "data: three\n\n"];
    const sentAt: number[] = [];
    backend = await startBackend(async (_req, _body, res) => {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      for (const part of parts) {
        sentAt.push(performance.now());
        res.write(part);
        await sleep(150);
      }
      res.end();
    });
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(authed("http://localhost:3000/api/stream"), ctx("stream"));
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/event-stream");

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    const received: { text: string; at: number }[] = [];
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      received.push({ text: decoder.decode(value), at: performance.now() });
    }

    // Each part arrives as its own chunk, in order.
    expect(received.map((chunk) => chunk.text)).toEqual(parts);
    // Each part reaches the client before the backend sends the next one,
    // so the proxy did not wait for the full response.
    for (let i = 0; i < parts.length - 1; i++) {
      expect(received[i].at).toBeLessThan(sentAt[i + 1]);
    }
  });

  it("keeps the event-stream content type and streams a POST chat answer in parts", async () => {
    const parts = [
      'event: delta\ndata: {"text":"one"}\n\n',
      'event: delta\ndata: {"text":"two"}\n\n',
      "event: done\ndata: {}\n\n",
    ];
    const sentAt: number[] = [];
    backend = await startBackend(async (_req, _body, res) => {
      res.writeHead(200, { "Content-Type": "text/event-stream; charset=utf-8" });
      for (const part of parts) {
        sentAt.push(performance.now());
        res.write(part);
        await sleep(150);
      }
      res.end();
    });
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await POST(
      authed("http://localhost:3000/api/chat", {
        method: "POST",
        headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
        body: JSON.stringify({ message: "/push buy milk" }),
      }),
      ctx("chat"),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/event-stream; charset=utf-8");
    expect(response.headers.get("Cache-Control")).toBe("no-cache");
    expect(response.headers.get("X-Accel-Buffering")).toBe("no");
    // The backend sees the event-stream Accept header and the message body.
    expect(backend.requests[0].headers.accept).toBe("text/event-stream");
    expect(JSON.parse(backend.requests[0].body)).toEqual({ message: "/push buy milk" });

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    const received: { text: string; at: number }[] = [];
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      received.push({ text: decoder.decode(value), at: performance.now() });
    }

    expect(received.map((chunk) => chunk.text)).toEqual(parts);
    for (let i = 0; i < parts.length - 1; i++) {
      expect(received[i].at).toBeLessThan(sentAt[i + 1]);
    }
  });
});
