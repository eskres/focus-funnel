import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getSession, getAccessToken } = vi.hoisted(() => ({
  getSession: vi.fn(),
  getAccessToken: vi.fn(),
}));

vi.mock("@/lib/auth0", () => ({
  auth0: { getSession, getAccessToken },
}));

import { DELETE, GET, PUT } from "./route";

type Handler = (req: IncomingMessage, body: string, res: import("node:http").ServerResponse) => void;

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
      new Request("http://localhost:3000/api/settings/api-key?x=1&y=two", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Cookie: "appSession=secret-session",
          Authorization: "Bearer client-supplied",
        },
        body: JSON.stringify({ api_key: "nebius-key-abcd" }),
      }),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ saved: true, last4: "abcd" });
    expect(response.headers.get("Cache-Control")).toBe("no-cache");
    expect(response.headers.get("X-Accel-Buffering")).toBe("no");

    expect(backend.requests).toHaveLength(1);
    const [forwarded] = backend.requests;
    expect(forwarded.method).toBe("PUT");
    expect(forwarded.url).toBe("/api/settings/api-key?x=1&y=two");
    expect(forwarded.body).toBe(JSON.stringify({ api_key: "nebius-key-abcd" }));
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
      new Request("http://localhost:3000/api/settings/api-key", { method: "DELETE" }),
    );

    expect(response.status).toBe(204);
    expect(await response.text()).toBe("");
    expect(backend.requests[0].method).toBe("DELETE");
  });

  it.each([
    ["no session", () => getSession.mockResolvedValue(null)],
    [
      "a session whose token cannot be refreshed",
      () => getAccessToken.mockRejectedValue(new Error("failed_to_refresh_token")),
    ],
  ])("returns 401 unauthenticated without calling the backend for %s", async (_name, setup) => {
    setup();
    backend = await startBackend((_req, _body, res) => {
      res.writeHead(200);
      res.end("{}");
    });
    vi.stubEnv("BACKEND_URL", backend.url);

    const response = await GET(new Request("http://localhost:3000/api/me"));

    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({
      error: { code: "unauthenticated", message: expect.any(String) },
    });
    expect(backend.requests).toHaveLength(0);
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

    const response = await GET(new Request("http://localhost:3000/api/stream"));
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
