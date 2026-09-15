import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  apiFetch,
  NebiusKeyMissingError,
  UnauthenticatedError,
} from "./api";

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("turns nebius_key_missing into NebiusKeyMissingError", async () => {
    mockFetch(
      jsonResponse(400, {
        error: { code: "nebius_key_missing", message: "Add a Nebius API key." },
      }),
    );

    const error = await apiFetch("/api/chat").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(NebiusKeyMissingError);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      code: "nebius_key_missing",
      message: "Add a Nebius API key.",
      status: 400,
    });
  });

  it("turns unauthenticated into UnauthenticatedError", async () => {
    mockFetch(
      jsonResponse(401, {
        error: { code: "unauthenticated", message: "Log in to continue." },
      }),
    );

    const error = await apiFetch("/api/me").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(UnauthenticatedError);
    expect(error).toMatchObject({ code: "unauthenticated", status: 401 });
  });

  it("uses a generic ApiError for unknown codes and non-JSON bodies", async () => {
    mockFetch(new Response("Bad gateway", { status: 502 }));

    const error = await apiFetch("/api/me").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeInstanceOf(UnauthenticatedError);
    expect(error).toMatchObject({ code: "unknown_error", status: 502 });
  });

  it("returns parsed JSON and sends JSON bodies", async () => {
    const fetchMock = mockFetch(jsonResponse(200, { saved: false }));

    const result = await apiFetch<{ saved: boolean }>("/api/settings/api-key", {
      method: "PUT",
      body: JSON.stringify({ api_key: "k" }),
    });

    expect(result).toEqual({ saved: false });
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/settings/api-key");
    expect(new Headers(init.headers).get("Content-Type")).toBe(
      "application/json",
    );
  });

  it("returns undefined for 204 responses", async () => {
    mockFetch(new Response(null, { status: 204 }));

    await expect(
      apiFetch("/api/settings/api-key", { method: "DELETE" }),
    ).resolves.toBeUndefined();
  });
});
