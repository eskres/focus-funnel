import { afterEach, describe, expect, it, vi } from "vitest";

import { delta, done, errorResponse, fakeApi, streamOf, toolEvent } from "@/test/fake-api";

import { BackendUnreachableError, NotFoundError, ModelNotSetError, SpendCapReachedError } from "./api";
import { COMMANDS, followTurn, isDeleteCommand, streamChat } from "./chat";
import { browserTimeZone } from "./time-zone";

afterEach(() => {
  vi.unstubAllGlobals();
});

async function drain(iterator: AsyncGenerator<unknown>) {
  const events = [];
  for await (const event of iterator) events.push(event);
  return events;
}

describe("streamChat", () => {
  it("sends the conversation and the chosen model with the message", async () => {
    const fetchMock = vi.fn(async () => new Response("event: done\ndata: {}\n\n", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const events = await drain(
      streamChat({
        message: "hello",
        conversationId: "c1",
        choice: { providerId: "nebius", model: "vendor/big", reasoningEffort: "low" },
      }),
    );

    expect(events).toEqual([{ type: "done" }]);
    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/api/chat");
    expect(JSON.parse(String(init.body))).toEqual({
      message: "hello",
      time_zone: browserTimeZone(),
      conversation_id: "c1",
      provider_id: "nebius",
      model: "vendor/big",
      reasoning_effort: "low",
    });
  });

  it("sends only the message and the zone for a new conversation with no choice", async () => {
    const fetchMock = vi.fn(async () => new Response("", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await drain(streamChat({ message: "hi" }));

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ message: "hi", time_zone: browserTimeZone() });
  });

  it("reports the conversation a refused message was stored in, then throws", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          { error: { code: "model_not_set", message: "No chat model is set." } },
          { status: 409, headers: { "X-Conversation-Id": "c9" } },
        ),
      ),
    );
    const stored = vi.fn();

    const error = await drain(streamChat({ message: "hi" }, undefined, stored)).catch((e) => e);

    expect(stored).toHaveBeenCalledWith("c9");
    expect(error).toBeInstanceOf(ModelNotSetError);
  });

  it("reports the new conversation a message refused at the spend cap was stored in", async () => {
    const message = "Your monthly spend cap of $5.00 is reached.";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => errorResponse(409, "spend_cap_reached", message, { "X-Conversation-Id": "c1" })),
    );
    const stored = vi.fn();

    const error = await drain(streamChat({ message: "hi" }, undefined, stored)).catch((e) => e);

    expect(stored).toHaveBeenCalledWith("c1");
    expect(error).toBeInstanceOf(SpendCapReachedError);
    expect(error).toMatchObject({ message, status: 409 });
  });
});

describe("followTurn", () => {
  it("yields the running answer's events from the first, through the terminal event", async () => {
    const { calls, fetchMock } = fakeApi({
      "GET /api/chat/c1/stream": streamOf(
        toolEvent("search_thoughts", "start"),
        toolEvent("search_thoughts", "end", "Searched"),
        delta("Hal"),
        delta("f."),
        done,
      ),
    });

    const events = await drain(followTurn("c1"));

    expect(events).toEqual([
      { type: "tool", name: "search_thoughts", phase: "start" },
      { type: "tool", name: "search_thoughts", phase: "end", summary: "Searched" },
      { type: "delta", text: "Hal" },
      { type: "delta", text: "f." },
      { type: "done" },
    ]);
    expect(calls).toEqual([{ method: "GET", path: "/api/chat/c1/stream", body: undefined }]);
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init.headers).get("Accept")).toBe("text/event-stream");
  });

  it("yields nothing when no answer is running (204)", async () => {
    fakeApi({ "GET /api/chat/c1/stream": new Response(null, { status: 204 }) });

    await expect(drain(followTurn("c1"))).resolves.toEqual([]);
  });

  it("throws NotFoundError for a conversation that is not the user's (404)", async () => {
    fakeApi({ "GET /api/chat/c9/stream": errorResponse(404, "not_found", "Not found.") });

    const error = await drain(followTurn("c9")).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(NotFoundError);
    expect(error).toMatchObject({ code: "not_found", message: "Not found.", status: 404 });
  });

  it("throws BackendUnreachableError when the server cannot be reached", async () => {
    fakeApi({
      "GET /api/chat/c1/stream": () => {
        throw new TypeError("Failed to fetch");
      },
    });

    await expect(drain(followTurn("c1"))).rejects.toBeInstanceOf(BackendUnreachableError);
  });

  it("passes the signal on, so leaving stops only the following", async () => {
    const { fetchMock } = fakeApi({ "GET /api/chat/c1/stream": streamOf(done) });
    const controller = new AbortController();

    await drain(followTurn("c1", controller.signal));

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.signal).toBe(controller.signal);
  });
});

describe("commands", () => {
  it("lists /push, /pull, /explore, and /compact, and never /delete", () => {
    expect(COMMANDS.map((c) => c.command)).toEqual(["/push", "/pull", "/explore", "/compact"]);
  });

  it.each(["/delete", "  /DELETE ", "/Delete\n"])("recognises %j as /delete", (text) => {
    expect(isDeleteCommand(text)).toBe(true);
  });

  it.each(["/delete now", "/deleted", "please /delete"])("does not treat %j as /delete", (text) => {
    expect(isDeleteCommand(text)).toBe(false);
  });
});
