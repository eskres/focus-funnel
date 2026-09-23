import { afterEach, describe, expect, it, vi } from "vitest";

import { ModelNotSetError } from "./api";
import { COMMANDS, isDeleteCommand, streamChat } from "./chat";

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
      conversation_id: "c1",
      provider_id: "nebius",
      model: "vendor/big",
      reasoning_effort: "low",
    });
  });

  it("sends only the message for a new conversation with no choice", async () => {
    const fetchMock = vi.fn(async () => new Response("", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await drain(streamChat({ message: "hi" }));

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ message: "hi" });
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
