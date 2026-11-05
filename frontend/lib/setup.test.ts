import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  NotFoundError,
  SetupIncompleteError,
  SetupTokenInvalidError,
} from "./api";
import { finishSetup, getSetupStatus } from "./setup";

const TOKEN = "setup-token-0123456789abcdefghij";

function jsonResponse(status: number, body: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const refusal = (status: number, code: string, message: string) =>
  jsonResponse(status, { error: { code, message } });

function mockFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function sent(fetchMock: ReturnType<typeof mockFetch>) {
  const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return { path, method: init.method ?? "GET", headers: new Headers(init.headers) };
}

const status = {
  auth_mode: "oidc",
  ready: false,
  items: [
    {
      id: "database",
      state: "ok",
      required: true,
      message: "Postgres answers and has pgvector 0.8.1.",
      settings: ["DATABASE_URL"],
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

const REFUSALS = [
  [403, "setup_token_invalid", SetupTokenInvalidError],
  [404, "not_found", NotFoundError],
  [409, "setup_incomplete", SetupIncompleteError],
] as const;

describe("getSetupStatus", () => {
  it("sends the token in X-Setup-Token and returns the status", async () => {
    const fetchMock = mockFetch(jsonResponse(200, status));

    expect(await getSetupStatus(TOKEN)).toEqual(status);

    const request = sent(fetchMock);
    expect(request.path).toBe("/api/setup/status");
    expect(request.method).toBe("GET");
    expect(request.headers.get("X-Setup-Token")).toBe(TOKEN);
  });

  it("sends no header without a token", async () => {
    const fetchMock = mockFetch(refusal(404, "not_found", "Not found."));

    await getSetupStatus(null).catch(() => undefined);

    expect(sent(fetchMock).headers.has("X-Setup-Token")).toBe(false);
  });

  it.each(REFUSALS)("raises the error class for %i %s", async (code, name, ErrorClass) => {
    mockFetch(refusal(code, name, `refused with ${name}`));

    const error = await getSetupStatus(TOKEN).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ErrorClass);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: name, status: code, message: `refused with ${name}` });
  });
});

describe("finishSetup", () => {
  it("posts with the token in X-Setup-Token and resolves on 204", async () => {
    const fetchMock = mockFetch(new Response(null, { status: 204 }));

    await expect(finishSetup(TOKEN)).resolves.toBeUndefined();

    const request = sent(fetchMock);
    expect(request.path).toBe("/api/setup/complete");
    expect(request.method).toBe("POST");
    expect(request.headers.get("X-Setup-Token")).toBe(TOKEN);
  });

  it.each(REFUSALS)("raises the error class for %i %s", async (code, name, ErrorClass) => {
    mockFetch(refusal(code, name, `refused with ${name}`));

    const error = await finishSetup(TOKEN).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ErrorClass);
    expect(error).toMatchObject({ code: name, status: code, message: `refused with ${name}` });
  });
});
