import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  apiFetch,
  BackendUnreachableError,
  DemoFullError,
  DemoSessionExpiredError,
  InternalError,
  NotAllowedError,
  RateLimitedError,
  ProviderKeyMissingError,
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
  it("turns provider_key_missing into ProviderKeyMissingError", async () => {
    mockFetch(
      jsonResponse(400, {
        error: { code: "provider_key_missing", message: "Add a Nebius API key." },
      }),
    );

    const error = await apiFetch("/api/chat").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ProviderKeyMissingError);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      code: "provider_key_missing",
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

  it.each([
    ["backend_unreachable", 502, BackendUnreachableError],
    ["internal_error", 500, InternalError],
    ["not_allowed", 403, NotAllowedError],
    ["demo_session_expired", 401, DemoSessionExpiredError],
    ["demo_full", 503, DemoFullError],
    ["rate_limited", 429, RateLimitedError],
  ])("turns %s into its error class", async (code, status, ErrorClass) => {
    mockFetch(jsonResponse(status, { error: { code, message: "Try again." } }));

    const error = await apiFetch("/api/me").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ErrorClass);
    expect(error).toMatchObject({ code, message: "Try again.", status });
  });

  it.each(["constructor", "__proto__", "toString"])(
    "uses a plain ApiError for the inherited property name %s",
    async (code) => {
      mockFetch(
        new Response(`{"error":{"code":${JSON.stringify(code)},"message":"odd"}}`, {
          status: 400,
        }),
      );

      const error = await apiFetch("/api/me").catch((e: unknown) => e);

      expect(error).toBeInstanceOf(ApiError);
      expect(Object.getPrototypeOf(error)).toBe(ApiError.prototype);
      expect(error).toMatchObject({ code, message: "odd", status: 400 });
    },
  );

  it("returns parsed JSON and sends JSON bodies", async () => {
    const fetchMock = mockFetch(jsonResponse(200, { saved: false }));

    const result = await apiFetch<{ saved: boolean }>("/api/providers/nebius/key", {
      method: "PUT",
      body: JSON.stringify({ key: "k" }),
    });

    expect(result).toEqual({ saved: false });
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/providers/nebius/key");
    expect(new Headers(init.headers).get("Content-Type")).toBe(
      "application/json",
    );
  });

  it("returns undefined for 204 responses", async () => {
    mockFetch(new Response(null, { status: 204 }));

    await expect(
      apiFetch("/api/providers/nebius/key", { method: "DELETE" }),
    ).resolves.toBeUndefined();
  });
});

describe("createApiError", () => {
  it.each([
    ["model_not_set", "ModelNotSetError"],
    ["model_unknown", "ModelUnknownError"],
    ["model_unsupported", "ModelUnsupportedError"],
    ["model_unavailable", "ModelUnavailableError"],
    ["context_full", "ContextFullError"],
    ["conversation_busy", "ConversationBusyError"],
    ["output_limit_reached", "OutputLimitReachedError"],
    ["tool_loop_limit", "ToolLoopLimitError"],
  ])("turns %s into %s", async (code, className) => {
    const api = await import("./api");
    const ErrorClass = api[className as keyof typeof api] as typeof ApiError;
    const error = api.createApiError(code, "A message.", 409);
    expect(error).toBeInstanceOf(ErrorClass);
    expect(error).toMatchObject({ code, message: "A message.", status: 409 });
  });

  it("keeps an unknown code as a plain ApiError", async () => {
    const { createApiError } = await import("./api");
    const error = createApiError("something_new", "x", 400);
    expect(error.constructor).toBe(ApiError);
  });
});
