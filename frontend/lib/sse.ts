// Parses the chat event stream (`POST /api/chat`) into typed events.
// The backend sends named events, each with a JSON payload:
//   event: conversation  data: {"id":"...","title":"..."}    first, for a new conversation
//   event: tool          data: {"name":"...","phase":"start"|"end","summary":"...","sources":[...],"failed":true}
//                        (a connector tool is named "<connector>__<tool>"; failed marks a connector failure)
//   event: proposal      data: {"id":"...","position":2,"parts":[{"title","summary","tags","category","when","when_choices","thought_id","saved_title","deleted","add_to","based_on","target","similar","added","undone","mark"}],"replaced_by":null,"replaces":"..."|null}
//   event: action        data: {"id":"...","position":2,"connector_id":"..."|null,"connector":"calendar","tool":"create_event",
//                              "title":"..."|null,"arguments":{...},"status":"pending","result":null,"error_code":null}
//                        (a connector tool call waiting for the user's approval: its card)
//   event: delta         data: {"text":"..."}
//   event: usage         data: {"prompt_tokens":1,"completion_tokens":1,"context_length":1}
//   event: notice        data: {"kind":"compact_suggested"|"usage_warning", ...}
//   event: compact_draft data: {"summary":"...","through_position":3,"provider_id":"...","model":"..."}
//   event: compact_models data: {"needed_tokens":1,"context_length":1,"models":[{"provider_id":"...","model":"...","context_length":1}]}
//   event: error         data: {"error":{"code":"...","message":"..."}}
//   event: done          data: {}

import type { When } from "@/lib/dates";

/**
 * One part of a proposal: one card. `thoughtId` is set once it is saved.
 * `savedTitle` is the saved thought's current title, and `deleted` is true
 * when the saved thought is gone; both are empty for an unsaved part.
 * `when` is the proposed date; `whenChoices` holds two dates when the model
 * found the day unclear, for the user to pick one (or no date).
 */
export type ProposalPart = {
  title: string;
  summary: string;
  tags: string[];
  category: string | null;
  when: When | null;
  whenChoices: When[] | null;
  thoughtId: string | null;
  savedTitle: string | null;
  deleted: boolean;
  /**
   * For an addition, the filed thought it adds to, and that thought's
   * `updated_at` when the proposal was written, kept as the server's string
   * so a confirm sends it back unchanged. Null for a new thought.
   */
  addTo: string | null;
  basedOn: string | null;
  /** For an addition, the thought it adds to as it is now, or `{ deleted: true }`. */
  target: Target | { deleted: true } | null;
  /** For a new thought, the strong match the "Similar" hint names, or null. */
  similar: (Target & { thoughtId: string }) | null;
  /** Saved as an addition, and that addition undone since. */
  added: boolean;
  undone: boolean;
  /**
   * For a status part, the thought it marks done; null for a new thought or
   * an addition. Its `target` names the thought as it is now.
   */
  mark: string | null;
};

/** A filed thought as an addition card shows it. `updatedAt` is its version, as the server sent it. */
export type Target = {
  title: string;
  summary: string;
  tags: string[];
  category: string | null;
  createdAt: string;
  updatedAt: string;
};

/**
 * What one propose_thought call proposed. `position` is its tool message's.
 * `replacedBy` is the later proposal that replaced it while it was held.
 */
export type Proposal = {
  id: string;
  position: number;
  parts: ProposalPart[];
  replacedBy: string | null;
};

/** Where an action is: waiting, running, or how it ended. */
export type ActionStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "unknown"
  | "declined"
  | "expired";

const ACTION_STATUSES: ActionStatus[] = [
  "pending",
  "running",
  "done",
  "failed",
  "unknown",
  "declined",
  "expired",
];

/**
 * A connector tool call that waits for, or had, the user's approval: its card.
 * `position` is its tool message's. `result` is what the server returned when
 * done, why it did not run when failed, or why there is no outcome when unknown
 * (the call was sent, then timed out or was interrupted, so it may have run). `errorCode` is the connector failure
 * code, or `tool_error` when the server ran the tool and reported an error.
 */
export type Action = {
  id: string;
  position: number;
  connector: string;
  tool: string;
  title: string | null;
  arguments: Record<string, unknown>;
  status: ActionStatus;
  result: string | null;
  errorCode: string | null;
};

/** A thought a search showed the model, listed under the answer. */
export type Source = { id: string; title: string; createdAt: string; tags: string[] };

/** A loadout model large enough to write a /compact summary. */
export type CompactModel = { providerId: string; model: string; contextLength: number };

export type SseEvent =
  | { type: "conversation"; id: string; title: string }
  | {
      type: "tool";
      name: string;
      phase: "start" | "end";
      summary?: string;
      sources?: Source[];
      failed?: boolean;
    }
  /** `replaces`: the earlier proposal whose cards now show as replaced. */
  | ({ type: "proposal"; replaces: string | null } & Proposal)
  | { type: "action"; action: Action }
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

function toWhen(value: unknown): When | null {
  return isRecord(value) && typeof value.start === "string"
    ? {
        start: value.start,
        end: typeof value.end === "string" ? value.end : null,
        time_zone: typeof value.time_zone === "string" ? value.time_zone : "UTC",
      }
    : null;
}

function toTarget(value: unknown): Target | null {
  return isRecord(value) &&
    typeof value.title === "string" &&
    typeof value.summary === "string" &&
    isStringArray(value.tags) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
    ? {
        title: value.title,
        summary: value.summary,
        tags: value.tags,
        category: typeof value.category === "string" ? value.category : null,
        createdAt: value.created_at,
        updatedAt: value.updated_at,
      }
    : null;
}

/** Two or more dates to pick from; null for none, as an older server sends. */
function toWhenChoices(value: unknown): When[] | null {
  if (!Array.isArray(value)) return null;
  const choices = value.map(toWhen).filter((when): when is When => when !== null);
  return choices.length > 0 ? choices : null;
}

function toSimilar(value: unknown): (Target & { thoughtId: string }) | null {
  const target = toTarget(value);
  return target && isRecord(value) && typeof value.thought_id === "string"
    ? { ...target, thoughtId: value.thought_id }
    : null;
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
        // An older server sends neither field: no date.
        when: toWhen(value.when),
        whenChoices: toWhenChoices(value.when_choices),
        thoughtId: typeof value.thought_id === "string" ? value.thought_id : null,
        // An older server sends neither field.
        savedTitle: typeof value.saved_title === "string" ? value.saved_title : null,
        deleted: value.deleted === true,
        // An older server sends none of these, and the part is a new thought.
        addTo: typeof value.add_to === "string" ? value.add_to : null,
        basedOn: typeof value.based_on === "string" ? value.based_on : null,
        target:
          isRecord(value.target) && value.target.deleted === true
            ? { deleted: true }
            : toTarget(value.target),
        similar: toSimilar(value.similar),
        added: value.added === true,
        undone: value.undone === true,
        // An older server sends no mark: not a status part.
        mark: typeof value.mark === "string" ? value.mark : null,
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
  return {
    id: value.id,
    position: value.position,
    parts: parts as ProposalPart[],
    replacedBy: typeof value.replaced_by === "string" ? value.replaced_by : null,
  };
}

/** An action as the server sends it: in the event, the stored conversation, and the approval's answer. */
export function toAction(value: unknown): Action | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.position !== "number" ||
    typeof value.connector !== "string" ||
    typeof value.tool !== "string" ||
    !isRecord(value.arguments) ||
    !ACTION_STATUSES.includes(value.status as ActionStatus)
  ) {
    return null;
  }
  return {
    id: value.id,
    position: value.position,
    connector: value.connector,
    tool: value.tool,
    title: typeof value.title === "string" ? value.title : null,
    arguments: value.arguments,
    status: value.status as ActionStatus,
    result: typeof value.result === "string" ? value.result : null,
    errorCode: typeof value.error_code === "string" ? value.error_code : null,
  };
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
          ...(payload.failed === true ? { failed: true } : {}),
        };
      }
      return null;
    case "proposal": {
      const proposal = toProposal(payload);
      return proposal
        ? {
            type: "proposal",
            ...proposal,
            replaces: typeof payload.replaces === "string" ? payload.replaces : null,
          }
        : null;
    }
    case "action": {
      const action = toAction(payload);
      return action ? { type: "action", action } : null;
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
