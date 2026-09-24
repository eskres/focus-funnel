import { describe, expect, it } from "vitest";

import { parseSse, type SseEvent } from "./sse";

const encoder = new TextEncoder();

function streamOf(...chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      }
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<SseEvent[]> {
  const events: SseEvent[] = [];
  for await (const event of parseSse(stream)) events.push(event);
  return events;
}

const wire =
  'event: conversation\ndata: {"id":"c1","title":"buy oat milk"}\n\n' +
  'event: tool\ndata: {"name":"search_thoughts","phase":"start"}\n\n' +
  'event: tool\ndata: {"name":"search_thoughts","phase":"end","summary":"Searched"}\n\n' +
  'event: proposal\ndata: {"title":"Oat milk","summary":"Buy it.","tags":["shopping"]}\n\n' +
  'event: delta\ndata: {"text":"Hel"}\n\n' +
  'event: delta\ndata: {"text":"lo"}\n\n' +
  'event: usage\ndata: {"prompt_tokens":550,"completion_tokens":36,"context_length":131072}\n\n' +
  'event: notice\ndata: {"kind":"compact_suggested"}\n\n' +
  "event: done\ndata: {}\n\n";

const expected: SseEvent[] = [
  { type: "conversation", id: "c1", title: "buy oat milk" },
  { type: "tool", name: "search_thoughts", phase: "start" },
  { type: "tool", name: "search_thoughts", phase: "end", summary: "Searched" },
  { type: "proposal", title: "Oat milk", summary: "Buy it.", tags: ["shopping"] },
  { type: "delta", text: "Hel" },
  { type: "delta", text: "lo" },
  { type: "usage", promptTokens: 550, completionTokens: 36, contextLength: 131072 },
  { type: "notice", kind: "compact_suggested", data: { kind: "compact_suggested" } },
  { type: "done" },
];

describe("parseSse", () => {
  it("parses each event in order", async () => {
    expect(await collect(streamOf(wire))).toEqual(expected);
  });

  it("parses the /compact draft and the larger-model choice", async () => {
    const events = await collect(
      streamOf(
        'event: compact_draft\ndata: {"summary":"Rent is 900.","through_position":3,"provider_id":"nebius","model":"vendor/nano"}\n\n' +
          'event: compact_models\ndata: {"needed_tokens":9000,"context_length":8192,"models":[{"provider_id":"nebius","model":"vendor/big","context_length":262144}]}\n\n' +
          'event: compact_models\ndata: {"needed_tokens":9000,"context_length":null,"models":[]}\n\n',
      ),
    );
    expect(events).toEqual([
      {
        type: "compact_draft",
        summary: "Rent is 900.",
        throughPosition: 3,
        providerId: "nebius",
        model: "vendor/nano",
      },
      {
        type: "compact_models",
        neededTokens: 9000,
        contextLength: 8192,
        models: [{ providerId: "nebius", model: "vendor/big", contextLength: 262144 }],
      },
      { type: "compact_models", neededTokens: 9000, contextLength: null, models: [] },
    ]);
  });

  it("skips a compact event with a malformed payload", async () => {
    const events = await collect(
      streamOf(
        'event: compact_draft\ndata: {"summary":"No position"}\n\n' +
          'event: compact_models\ndata: {"needed_tokens":1,"models":[{"model":"x"}]}\n\n',
      ),
    );
    expect(events).toEqual([]);
  });

  it("parses an error event into its code and message", async () => {
    const events = await collect(
      streamOf('event: error\ndata: {"error":{"code":"provider_key_rejected","message":"No."}}\n\n'),
    );
    expect(events).toEqual([{ type: "error", code: "provider_key_rejected", message: "No." }]);
  });

  it("leaves out a usage event's context length when the model has none", async () => {
    const events = await collect(
      streamOf('event: usage\ndata: {"prompt_tokens":1,"completion_tokens":2}\n\n'),
    );
    expect(events).toEqual([{ type: "usage", promptTokens: 1, completionTokens: 2 }]);
  });

  it("parses events split across chunk boundaries", async () => {
    // Every possible single split point, including inside a field name,
    // inside the JSON, and between the two newlines that end an event.
    for (let i = 1; i < wire.length; i++) {
      const events = await collect(streamOf(wire.slice(0, i), wire.slice(i)));
      expect(events, `split at ${i}`).toEqual(expected);
    }
  });

  it("parses events delivered one byte at a time", async () => {
    const bytes = encoder.encode(wire);
    const chunks = Array.from(bytes, (byte) => new Uint8Array([byte]));
    expect(await collect(streamOf(...chunks))).toEqual(expected);
  });

  it("keeps a multi-byte character that is split across chunks", async () => {
    const bytes = encoder.encode('event: delta\ndata: {"text":"æøå €"}\n\n');
    const middle = bytes.indexOf(0xc3) + 1; // between the two bytes of "æ"
    const events = await collect(streamOf(bytes.slice(0, middle), bytes.slice(middle)));
    expect(events).toEqual([{ type: "delta", text: "æøå €" }]);
  });

  it("accepts CRLF line endings", async () => {
    const events = await collect(streamOf(wire.replaceAll("\n", "\r\n")));
    expect(events).toEqual(expected);
  });

  it("ignores an unknown event name and keeps parsing", async () => {
    const events = await collect(
      streamOf(
        'event: delta\ndata: {"text":"a"}\n\n' +
          'event: routing\ndata: {"gate":"push"}\n\n' +
          'event: delta\ndata: {"text":"b"}\n\n',
      ),
    );
    expect(events).toEqual([
      { type: "delta", text: "a" },
      { type: "delta", text: "b" },
    ]);
  });

  it("ignores comments, malformed payloads, and payloads of the wrong shape", async () => {
    const events = await collect(
      streamOf(
        ": keep-alive\n\n" +
          "event: delta\ndata: not json\n\n" +
          'event: delta\ndata: {"text":5}\n\n' +
          'event: tool\ndata: {"name":"x","phase":"middle"}\n\n' +
          'event: proposal\ndata: {"title":"x","summary":"y","tags":"z"}\n\n' +
          'event: error\ndata: {"error":{"code":5}}\n\n' +
          "event: done\ndata: {}\n\n",
      ),
    );
    expect(events).toEqual([{ type: "done" }]);
  });

  it("drops a final event that never received its closing blank line", async () => {
    const events = await collect(streamOf(wire + 'event: delta\ndata: {"text":"cut'));
    expect(events).toEqual(expected);
  });

  it("yields events before the stream ends", async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      },
    });
    const iterator = parseSse(stream);

    controller.enqueue(encoder.encode('event: delta\ndata: {"text":"first"}\n\n'));
    expect(await iterator.next()).toEqual({
      done: false,
      value: { type: "delta", text: "first" },
    });

    controller.close();
    expect(await iterator.next()).toEqual({ done: true, value: undefined });
  });
});
