import { describe, expect, it } from "vitest";

import { parseSse, type SseEvent, toProposal } from "./sse";

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
  'event: tool\ndata: {"name":"search_thoughts","phase":"end","summary":"Searched","sources":[{"id":"t1","title":"Oat milk","created_at":"2026-09-20T08:00:00+00:00","tags":["groceries"]}]}\n\n' +
  'event: proposal\ndata: {"id":"p1","position":2,"parts":[{"title":"Oat milk","summary":"Buy it.","tags":["shopping"],"category":"task","thought_id":null}],"replaced_by":null,"replaces":"p0"}\n\n' +
  'event: delta\ndata: {"text":"Hel"}\n\n' +
  'event: delta\ndata: {"text":"lo"}\n\n' +
  'event: usage\ndata: {"prompt_tokens":550,"completion_tokens":36,"context_length":131072}\n\n' +
  'event: notice\ndata: {"kind":"compact_suggested"}\n\n' +
  "event: done\ndata: {}\n\n";

const expected: SseEvent[] = [
  { type: "conversation", id: "c1", title: "buy oat milk" },
  { type: "tool", name: "search_thoughts", phase: "start" },
  {
    type: "tool",
    name: "search_thoughts",
    phase: "end",
    summary: "Searched",
    sources: [{ id: "t1", title: "Oat milk", createdAt: "2026-09-20T08:00:00+00:00", tags: ["groceries"] }],
  },
  {
    type: "proposal",
    id: "p1",
    position: 2,
    parts: [
      {
        title: "Oat milk",
        summary: "Buy it.",
        tags: ["shopping"],
        category: "task",
        // This server sends no date fields, as an older one does: no date.
        when: null,
        whenChoices: null,
        thoughtId: null,
        savedTitle: null,
        deleted: false,
        addTo: null,
        basedOn: null,
        target: null,
        similar: null,
        added: false,
        undone: false,
      },
    ],
    replacedBy: null,
    replaces: "p0",
  },
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
          'event: proposal\ndata: {"title":"x","summary":"y","tags":["z"]}\n\n' +
          'event: proposal\ndata: {"id":"p","position":1,"parts":[]}\n\n' +
          'event: proposal\ndata: {"id":"p","position":1,"parts":[{"title":"x","summary":"y","tags":"z"}]}\n\n' +
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

describe("toProposal", () => {
  const part = { title: "Oat milk", summary: "Buy it.", tags: [], category: null };

  it("reads a saved part's current title and a deleted part", () => {
    const proposal = toProposal({
      id: "p1",
      position: 2,
      parts: [
        { ...part, thought_id: "t1", saved_title: "Oat and soy milk", deleted: false },
        { ...part, thought_id: "t2", saved_title: null, deleted: true },
      ],
      replaced_by: null,
    });
    expect(proposal?.parts.map(({ thoughtId, savedTitle, deleted }) => ({ thoughtId, savedTitle, deleted }))).toEqual([
      { thoughtId: "t1", savedTitle: "Oat and soy milk", deleted: false },
      { thoughtId: "t2", savedTitle: null, deleted: true },
    ]);
  });

  it("reads a part from an older server, with neither field, as not changed", () => {
    const proposal = toProposal({ id: "p1", position: 2, parts: [{ ...part, thought_id: "t1" }] });
    expect(proposal?.parts[0]).toMatchObject({ thoughtId: "t1", savedTitle: null, deleted: false });
  });

  it("reads a part's date, and its two choices, with the zone the server stamped", () => {
    const dinner = { start: "2026-10-02T19:00", end: null, time_zone: "Europe/Oslo" };
    const later = { start: "2026-10-09T19:00", end: null, time_zone: "Europe/Oslo" };
    const proposal = toProposal({
      id: "p1",
      position: 2,
      parts: [
        { ...part, when: dinner, when_choices: null },
        { ...part, when: null, when_choices: [dinner, later] },
        { ...part, when: { start: "2026-11-03", end: "2026-11-06" }, when_choices: [] },
      ],
    });
    expect(proposal?.parts.map(({ when, whenChoices }) => ({ when, whenChoices }))).toEqual([
      { when: dinner, whenChoices: null },
      { when: null, whenChoices: [dinner, later] },
      { when: { start: "2026-11-03", end: "2026-11-06", time_zone: "UTC" }, whenChoices: null },
    ]);
  });

  const current = {
    title: "Buy new bike lock",
    summary: "Buy a lock.",
    tags: ["bike"],
    category: "task",
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00.123456+00:00",
  };

  it("reads an addition's target and version, keeping the version string as sent", () => {
    const proposal = toProposal({
      id: "p1",
      position: 2,
      parts: [
        {
          ...part,
          add_to: "t1",
          based_on: "2026-09-01T10:00:00.123456+00:00",
          target: current,
          similar: null,
          added: true,
          undone: true,
        },
        { ...part, add_to: "t2", based_on: "x", target: { deleted: true } },
      ],
    });
    expect(proposal?.parts[0]).toMatchObject({
      addTo: "t1",
      basedOn: "2026-09-01T10:00:00.123456+00:00",
      target: {
        title: "Buy new bike lock",
        summary: "Buy a lock.",
        tags: ["bike"],
        category: "task",
        createdAt: "2026-09-01T10:00:00Z",
        updatedAt: "2026-09-01T10:00:00.123456+00:00",
      },
      added: true,
      undone: true,
    });
    expect(proposal?.parts[1].target).toEqual({ deleted: true });
  });

  it("reads the strong match a new part names", () => {
    const proposal = toProposal({
      id: "p1",
      position: 2,
      parts: [{ ...part, similar: { ...current, thought_id: "t1" } }],
    });
    expect(proposal?.parts[0]).toMatchObject({
      addTo: null,
      target: null,
      similar: { thoughtId: "t1", title: "Buy new bike lock", updatedAt: current.updated_at },
    });
  });
});
