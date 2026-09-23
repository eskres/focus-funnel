// Parses the chat event stream (`POST /api/chat`) into typed events.
// The backend sends named events, each with a JSON payload:
//   event: delta    data: {"text":"..."}
//   event: error    data: {"error":{"code":"...","message":"..."}}
//   event: done     data: {}

export type SseEvent =
  | { type: "delta"; text: string }
  | { type: "error"; code: string; message: string }
  | { type: "done" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
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
    case "delta":
      return typeof payload.text === "string" ? { type: "delta", text: payload.text } : null;
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
