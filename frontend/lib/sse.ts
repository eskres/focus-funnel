// Parses the chat event stream (`POST /api/chat`) into typed events.
// The backend sends named events, each with a JSON payload:
//   event: conversation  data: {"id":"...","title":"..."}    first, for a new conversation
//   event: tool          data: {"name":"...","phase":"start"|"end","summary":"...","sources":[...]}
//   event: proposal      data: {"id":"...","position":2,"parts":[{"title","summary","tags","category","thought_id"}]}
//   event: delta         data: {"text":"..."}
//   event: usage         data: {"prompt_tokens":1,"completion_tokens":1,"context_length":1}
//   event: notice        data: {"kind":"compact_suggested"|"usage_warning", ...}
//   event: compact_draft data: {"summary":"...","through_position":3,"provider_id":"...","model":"..."}
//   event: compact_models data: {"needed_tokens":1,"context_length":1,"models":[{"provider_id":"...","model":"...","context_length":1}]}
//   event: error         data: {"error":{"code":"...","message":"..."}}
//   event: done          data: {}

/** One part of a proposal: one card. `thoughtId` is set once it is saved. */
export type ProposalPart = {
  title: string;
  summary: string;
  tags: string[];
  category: string | null;
  thoughtId: string | null;
};

/** What one propose_thought call proposed. `position` is its tool message's. */
export type Proposal = { id: string; position: number; parts: ProposalPart[] };

/** A thought a search showed the model, listed under the answer. */
export type Source = { id: string; title: string; createdAt: string; tags: string[] };

/** A loadout model large enough to write a /compact summary. */
export type CompactModel = { providerId: string; model: string; contextLength: number };

export type SseEvent =
  | { type: "conversation"; id: string; title: string }
  | { type: "tool"; name: string; phase: "start" | "end"; summary?: string; sources?: Source[] }
  | ({ type: "proposal" } & Proposal)
  | { type: "delta"; text: string }
  | { type: "usage"; promptTokens: number; completionTokens: number; contextLength?: number }
  | { type: "notice"; kind: string; data: Record<string, unknown> }
  | {
      type: "compact_draft";
      summary: string;
      throughPosition: number;
      providerId: string;
      model: string;
    }
  | {
      type: "compact_models";
      neededTokens: number;
      contextLength: number | null;
      models: CompactModel[];
    }
  | { type: "error"; code: string; message: string }
  | { type: "done" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function toPart(value: unknown): ProposalPart | null {
  return isRecord(value) &&
    typeof value.title === "string" &&
    typeof value.summary === "string" &&
    isStringArray(value.tags)
    ? {
        title: value.title,
        summary: value.summary,
        tags: value.tags,
        category: typeof value.category === "string" ? value.category : null,
        thoughtId: typeof value.thought_id === "string" ? value.thought_id : null,
      }
    : null;
}

/** A proposal as the server sends it, in the event and in the stored conversation. */
export function toProposal(value: unknown): Proposal | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.position !== "number" ||
    !Array.isArray(value.parts)
  ) {
    return null;
  }
  const parts = value.parts.map(toPart);
  if (parts.length === 0 || parts.some((part) => part === null)) return null;
  return { id: value.id, position: value.position, parts: parts as ProposalPart[] };
}

function toSource(value: unknown): Source | null {
  return isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.title === "string" &&
    typeof value.created_at === "string" &&
    isStringArray(value.tags)
    ? { id: value.id, title: value.title, createdAt: value.created_at, tags: value.tags }
    : null;
}

/** The sources a search returned, skipping any entry that does not fit. */
export function toSources(value: unknown): Source[] {
  if (!Array.isArray(value)) return [];
  return value.map(toSource).filter((source): source is Source => source !== null);
}

function toCompactModel(value: unknown): CompactModel | null {
  return isRecord(value) &&
    typeof value.provider_id === "string" &&
    typeof value.model === "string" &&
    typeof value.context_length === "number"
    ? { providerId: value.provider_id, model: value.model, contextLength: value.context_length }
    : null;
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
          ...(Array.isArray(payload.sources) ? { sources: toSources(payload.sources) } : {}),
        };
      }
      return null;
    case "proposal": {
      const proposal = toProposal(payload);
      return proposal ? { type: "proposal", ...proposal } : null;
    }
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
    case "compact_draft":
      return typeof payload.summary === "string" &&
        typeof payload.through_position === "number" &&
        typeof payload.provider_id === "string" &&
        typeof payload.model === "string"
        ? {
            type: "compact_draft",
            summary: payload.summary,
            throughPosition: payload.through_position,
            providerId: payload.provider_id,
            model: payload.model,
          }
        : null;
    case "compact_models": {
      if (typeof payload.needed_tokens !== "number" || !Array.isArray(payload.models)) return null;
      const models = payload.models.map(toCompactModel);
      if (models.some((model) => model === null)) return null;
      return {
        type: "compact_models",
        neededTokens: payload.needed_tokens,
        contextLength: typeof payload.context_length === "number" ? payload.context_length : null,
        models: models as CompactModel[],
      };
    }
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
