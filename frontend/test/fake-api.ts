// A fetch stand-in for component tests that answers by method and path.
import { act } from "@testing-library/react";
import { vi } from "vitest";

type Handler = (url: URL, init: RequestInit) => Response | Promise<Response>;

const encoder = new TextEncoder();

export const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

export const errorResponse = (
  status: number,
  code: string,
  message: string,
  headers: Record<string, string> = {},
) => json(status, { error: { code, message } }, headers);

export const delta = (text: string) => `event: delta\ndata: ${JSON.stringify({ text })}\n\n`;
export const done = "event: done\ndata: {}\n\n";
export const conversationEvent = (id: string, title: string) =>
  `event: conversation\ndata: ${JSON.stringify({ id, title })}\n\n`;
export const toolEvent = (
  name: string,
  phase: "start" | "end",
  summary?: string,
  sources?: WireSource[],
  failed?: boolean,
) =>
  `event: tool\ndata: ${JSON.stringify({
    name,
    phase,
    ...(summary ? { summary } : {}),
    ...(sources ? { sources } : {}),
    ...(failed ? { failed } : {}),
  })}\n\n`;

/** A date as the server sends it. */
export type WireWhen = { start: string; end: string | null; time_zone: string };

/** A proposal part as the server sends it. */
export type WirePart = {
  title: string;
  summary: string;
  tags: string[];
  category?: string | null;
  /** The proposed date; left out, as an older server does. */
  when?: WireWhen | null;
  /** Two dates for the user to pick from; left out, as an older server does. */
  when_choices?: WireWhen[] | null;
  thought_id?: string | null;
  /** The saved thought's current title; left out, as an older server does. */
  saved_title?: string | null;
  /** True when the saved thought was deleted; left out, as an older server does. */
  deleted?: boolean;
  /** An addition: the thought it adds to and its version; left out for a new thought. */
  add_to?: string | null;
  based_on?: string | null;
  target?: WireTarget | { deleted: true } | null;
  /** The strong match a new thought's "Similar" hint names. */
  similar?: (WireTarget & { thought_id: string }) | null;
  added?: boolean;
  undone?: boolean;
};

/** A filed thought as a proposal part's `target` or `similar` carries it. */
export type WireTarget = {
  title: string;
  summary: string;
  tags: string[];
  category: string | null;
  created_at: string;
  updated_at: string;
};

export const wireProposal = (
  id: string,
  parts: WirePart[],
  position = 2,
  replacedBy: string | null = null,
) => ({
  id,
  position,
  parts: parts.map((part) => ({ category: null, thought_id: null, ...part })),
  replaced_by: replacedBy,
});

export const proposalEvent = (
  id: string,
  parts: WirePart[],
  position = 2,
  replaces: string | null = null,
) =>
  `event: proposal\ndata: ${JSON.stringify({ ...wireProposal(id, parts, position), replaces })}\n\n`;

/** A connector action as the server sends it: in the event, on the conversation, and from the approval route. */
export const wireAction = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  position: 2,
  connector_id: "k1",
  connector: "calendar",
  tool: "create_event",
  title: "Create event",
  arguments: { summary: "Dentist", start: "2026-11-06T09:00", attendees: ["sam@example.com"] },
  status: "pending",
  result: null,
  error_code: null,
  ...extra,
});

export const actionEvent = (id: string, extra: Record<string, unknown> = {}) =>
  `event: action\ndata: ${JSON.stringify(wireAction(id, extra))}\n\n`;

/** A connector tool as `GET /api/connectors` lists it. */
export const wireTool = (name: string, extra: Record<string, unknown> = {}) => ({
  name,
  title: null,
  description: `Does ${name}.`,
  read_only_hint: true,
  available: true,
  enabled: true,
  acts: false,
  always_allow: false,
  reads_allowed: true,
  ...extra,
});

/** A connector as `GET /api/connectors` lists it. */
export const wireConnector = (
  id: string,
  name: string,
  tools: unknown[] = [],
  extra: Record<string, unknown> = {},
) => ({
  id,
  name,
  source: "user",
  url: `https://${name}.example.com/mcp`,
  auth_kind: "none",
  auth_header: null,
  auth_set: false,
  auth_last4: null,
  tools,
  tools_listed_at: "2026-11-01T10:00:00Z",
  ...extra,
});

/** The body of `GET /api/connectors`. */
export const connectorsListing = (connectors: unknown[], extra: Record<string, unknown> = {}) => ({
  connectors,
  user_connectors_allowed: true,
  catalog: [],
  warning_accepted: true,
  max_tools: 20,
  ...extra,
});

/** A source as the server sends it, in the tool event and on a stored tool message. */
export type WireSource = { id: string; title: string; created_at: string; tags: string[] };

export const source = (id: string, title: string, createdAt: string, tags: string[] = []): WireSource => ({
  id,
  title,
  created_at: createdAt,
  tags,
});
export const usageEvent = (promptTokens: number, contextLength?: number, completionTokens = 20) =>
  `event: usage\ndata: ${JSON.stringify({
    prompt_tokens: promptTokens,
    completion_tokens: completionTokens,
    ...(contextLength === undefined ? {} : { context_length: contextLength }),
  })}\n\n`;
export const noticeEvent = (data: Record<string, unknown>) =>
  `event: notice\ndata: ${JSON.stringify(data)}\n\n`;
export const compactDraftEvent = (summary: string, throughPosition: number, model = "vendor/nano") =>
  `event: compact_draft\ndata: ${JSON.stringify({
    summary,
    through_position: throughPosition,
    provider_id: "nebius",
    model,
  })}\n\n`;
export const compactModelsEvent = (
  contextLength: number | null,
  models: { model: string; context_length: number }[],
) =>
  `event: compact_models\ndata: ${JSON.stringify({
    needed_tokens: 9000,
    context_length: contextLength,
    models: models.map((m) => ({ provider_id: "nebius", ...m })),
  })}\n\n`;
export const errorEvent = (code: string, message: string) =>
  `event: error\ndata: ${JSON.stringify({ error: { code, message } })}\n\n`;

/** A response whose body the test feeds one part at a time. */
export function openStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }),
    push: (text: string) => act(async () => controller.enqueue(encoder.encode(text))),
    close: () => act(async () => controller.close()),
    fail: () => act(async () => controller.error(new TypeError("network error"))),
  };
}

/** A finished event stream. */
export const streamOf = (...parts: string[]) =>
  new Response(parts.join(""), { status: 200, headers: { "Content-Type": "text/event-stream" } });

export const loadout = (models: unknown[] = [], extra: Record<string, unknown> = {}) => ({
  models,
  temperature: null,
  temperature_default: 0.3,
  temperature_min: 0,
  temperature_max: 2,
  max_models: 5,
  model_hint: "Pick a model that supports tool calling.",
  ...extra,
});

export const loadoutEntry = (model: string, extra: Record<string, unknown> = {}) => ({
  provider_id: "nebius",
  model,
  reasoning_effort: null,
  is_default: false,
  efforts: ["none", "minimal", "low", "medium", "high"],
  ...extra,
});

export const summary = (id: string, title: string, extra: Record<string, unknown> = {}) => ({
  id,
  title,
  provider_id: "nebius",
  model: "vendor/nano",
  reasoning_effort: null,
  archived: false,
  last_activity_at: "2026-09-23T10:00:00Z",
  created_at: "2026-09-23T10:00:00Z",
  ...extra,
});

export const storedMessage = (
  position: number,
  role: string,
  content: string | null,
  extra: Record<string, unknown> = {},
) => ({
  id: `m${position}`,
  position,
  role,
  content,
  tool_calls: null,
  tool_call_id: null,
  status: "complete",
  error_code: null,
  compacted: false,
  details: null,
  created_at: "2026-09-23T10:00:00Z",
  ...extra,
});

/** A stored conversation with its messages and proposals. */
export const detail = (extra: Record<string, unknown> = {}) => ({
  ...summary("c1", "Milk"),
  last_prompt_tokens: null,
  held_proposal_id: null,
  context: { tokens: 0, estimated: true, context_length: null },
  messages: [],
  proposals: [],
  turn: null,
  ...extra,
});

/**
 * Installs a fetch mock. Routes are "METHOD /path" keys; a route's value is a
 * handler or a list of handlers used in turn (the last one repeats).
 * Unrouted calls fail the test loudly.
 */
export function fakeApi(routes: Record<string, Handler | Response | (Handler | Response)[]>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const counters = new Map<string, number>();
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const key = `${method} ${url.pathname}`;
    calls.push({
      method,
      path: url.pathname + url.search,
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
    });
    const route = routes[key];
    if (route === undefined) throw new Error(`Unexpected request: ${key}`);
    const list = Array.isArray(route) ? route : [route];
    const index = counters.get(key) ?? 0;
    counters.set(key, index + 1);
    const handler = list[Math.min(index, list.length - 1)];
    // A fixed response may be served more than once, so it is copied; a
    // handler makes a fresh one (and may hand out a live stream).
    return typeof handler === "function" ? handler(url, init) : handler.clone();
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls, routes };
}
