// Parses the chat event stream (`POST /api/chat`) into typed events.
// The backend sends named events, each with a JSON payload:
//   event: conversation  data: {"id":"...","title":"..."}    first, for a new conversation
//   event: tool          data: {"name":"...","phase":"start"|"end","summary":"..."}
//   event: proposal      data: {"title":"...","summary":"...","tags":["..."]}
//   event: delta         data: {"text":"..."}
//   event: usage         data: {"prompt_tokens":1,"completion_tokens":1,"context_length":1}
//   event: notice        data: {"kind":"compact_suggested"|"usage_warning", ...}
//   event: error         data: {"error":{"code":"...","message":"..."}}
//   event: done          data: {}

export type Proposal = { title: string; summary: string; tags: string[] };

export type SseEvent =
  | { type: "conversation"; id: string; title: string }
  | { type: "tool"; name: string; phase: "start" | "end"; summary?: string }
  | ({ type: "proposal" } & Proposal)
  | { type: "delta"; text: string }
  | { type: "usage"; promptTokens: number; completionTokens: number; contextLength?: number }
  | { type: "notice"; kind: string; data: Record<string, unknown> }
  | { type: "error"; code: string; message: string }
  | { type: "done" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function toEvent(name: string, data: string): SseEvent | null {
  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    return null;
  }
  if (!isRecord(payload)) return null;

  switch (name) {
    case "conversation":
      return typeof payload.id === "string" && typeof payload.title === "string"
        ? { type: "conversation", id: payload.id, title: payload.title }
        : null;
    case "tool":
      if (
        typeof payload.name === "string" &&
        (payload.phase === "start" || payload.phase === "end")
      ) {
        return {
          type: "tool",
          name: payload.name,
          phase: payload.phase,
          ...(typeof payload.summary === "string" ? { summary: payload.summary } : {}),
        };
      }
      return null;
    case "proposal":
      return typeof payload.title === "string" &&
        typeof payload.summary === "string" &&
        isStringArray(payload.tags)
        ? { type: "proposal", title: payload.title, summary: payload.summary, tags: payload.tags }
        : null;
    case "delta":
      return typeof payload.text === "string" ? { type: "delta", text: payload.text } : null;
    case "usage":
      if (
        typeof payload.prompt_tokens === "number" &&
        typeof payload.completion_tokens === "number"
      ) {
        return {
          type: "usage",
          promptTokens: payload.prompt_tokens,
          completionTokens: payload.completion_tokens,
          ...(typeof payload.context_length === "number"
            ? { contextLength: payload.context_length }
            : {}),
        };
      }
      return null;
    case "notice":
      return typeof payload.kind === "string"
        ? { type: "notice", kind: payload.kind, data: payload }
        : null;
    case "error": {
      const error = payload.error;
      if (isRecord(error) && typeof error.code === "string" && typeof error.message === "string") {
        return { type: "error", code: error.code, message: error.message };
      }
      return null;
    }
    case "done":
      return { type: "done" };
    default:
      // An event name this client does not know is skipped, so the backend can
      // add events without breaking older browsers.
      return null;
  }
}

/** Parses one event block (the text between blank lines), or null when it is not a known event. */
function parseBlock(block: string): SseEvent | null {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    // A line starting with ":" is a comment, used as a keep-alive.
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") name = value;
    else if (field === "data") data.push(value);
  }
  return data.length === 0 ? null : toEvent(name, data.join("\n"));
}

/**
 * Reads a byte stream and yields typed events as they complete. A chunk may
 * end anywhere, including inside an event or inside a multi-byte character,
 * so text is buffered until a blank line closes an event.
 */
export async function* parseSse(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent, void, undefined> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replaceAll("\r\n", "\n");

      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const event = parseBlock(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (event) yield event;
      }
      // A stream that ends without a closing blank line drops that last
      // partial event. The caller sees the missing `done` instead.
      if (done) return;
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}
