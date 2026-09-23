import {
  createServer,
  type IncomingMessage,
  type Server,
  type ServerResponse,
} from "node:http";
import type { AddressInfo } from "node:net";

import { AccessTokenError, AccessTokenErrorCode } from "@auth0/nextjs-auth0/errors";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getSession, getAccessToken } = vi.hoisted(() => ({
  getSession: vi.fn(),
  getAccessToken: vi.fn(),
}));

vi.mock("@/lib/auth0", () => ({
  auth0: { getSession, getAccessToken },
}));

import { DELETE, GET, PUT } from "./route";

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

beforeEach(() => {
  getSession.mockResolvedValue({ user: { sub: "auth0|user-1" } });
  getAccessToken.mockResolvedValue({ token: "test-access-token", expiresAt: 0 });
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
      new Request("http://localhost:3000/api/providers/nebius/key?x=1&y=two", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Cookie: "appSession=secret-session",
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
      new Request("http://localhost:3000/api/providers/nebius/key", { method: "DELETE" }),
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

    const response = await GET(new Request("http://localhost:3000/api/me"), ctx("me"));

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

    const response = await GET(new Request("http://localhost:3000/api/x"), ctx(...segments));

    expect(response.status).toBe(404);
    expect(await response.json()).toMatchObject({
      error: { code: "not_found", message: expect.any(String) },
    });
    expect(backend.requests).toHaveLength(0);
    expect(getAccessToken).not.toHaveBeenCalled();
  });

  it("encodes segments so they stay inside /api/ on the backend host", async () => {
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(
      new Request("http://localhost:3000/api/x"),
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
      new Request("http://localhost:3000/api/x"),
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

    const response = await GET(new Request("http://localhost:3000/api/me"), ctx("me"));

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

  it.each([
    ["no session", () => getSession.mockResolvedValue(null)],
    [
      "a session whose token cannot be refreshed",
      () =>
        getAccessToken.mockRejectedValue(
          new AccessTokenError(AccessTokenErrorCode.FAILED_TO_REFRESH_TOKEN, "refresh failed"),
        ),
    ],
  ])("returns 401 unauthenticated without calling the backend for %s", async (_name, setup) => {
    setup();
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(new Request("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({
      error: { code: "unauthenticated", message: expect.any(String) },
    });
    expect(backend.requests).toHaveLength(0);
  });

  it("returns 500 internal_error and logs when Auth0 fails for another reason", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    getSession.mockRejectedValue(new Error("discovery request failed"));
    backend = await startBackend(okBackend);
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(new Request("http://localhost:3000/api/me"), ctx("me"));

    expect(response.status).toBe(500);
    expect(await response.json()).toMatchObject({ error: { code: "internal_error" } });
    expect(backend.requests).toHaveLength(0);
    expect(consoleError).toHaveBeenCalledWith(
      "API proxy: could not get an access token",
      expect.objectContaining({ message: "discovery request failed" }),
    );
  });

  it("returns 502 backend_unreachable and logs without the token", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    backend = await startBackend(okBackend);
    const closedUrl = backend.url;
    await backend.close();
    backend = undefined;
    vi.stubEnv("BACKEND_URL", closedUrl);

    const response = await GET(new Request("http://localhost:3000/api/me"), ctx("me"));

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

    const response = await GET(new Request("http://localhost:3000/api/stream"), ctx("stream"));
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
});
