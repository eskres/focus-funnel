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
  'event: delta\ndata: {"text":"Hel"}\n\n' +
  'event: delta\ndata: {"text":"lo"}\n\n' +
  "event: done\ndata: {}\n\n";

const expected: SseEvent[] = [
  { type: "delta", text: "Hel" },
  { type: "delta", text: "lo" },
  { type: "done" },
];

describe("parseSse", () => {
  it("parses delta and done events in order", async () => {
    expect(await collect(streamOf(wire))).toEqual(expected);
  });

  it("parses an error event into its code and message", async () => {
    const events = await collect(
      streamOf('event: error\ndata: {"error":{"code":"provider_key_rejected","message":"No."}}\n\n'),
    );
    expect(events).toEqual([{ type: "error", code: "provider_key_rejected", message: "No." }]);
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
          'event: ping\ndata: {"anything":true}\n\n' +
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
