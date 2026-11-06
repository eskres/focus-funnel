// Typed client for the stored conversations (`/api/conversations`).
import { apiFetch } from "@/lib/api";
import type { When } from "@/lib/dates";
import {
  toAction,
  toProposal,
  toSources,
  type Action,
  type Proposal,
  type Source,
} from "@/lib/sse";
import { browserTimeZone } from "@/lib/time-zone";

export type ConversationSummary = {
  id: string;
  title: string;
  provider_id: string | null;
  model: string | null;
  reasoning_effort: string | null;
  archived: boolean;
  last_activity_at: string;
  created_at: string;
};

export type StoredToolCall = {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
};

export type StoredMessage = {
  id: string;
  position: number;
  role: "user" | "assistant" | "tool" | "summary";
  content: string | null;
  tool_calls: StoredToolCall[] | null;
  tool_call_id: string | null;
  /** `stopped`: the user stopped the answer (error code `answer_stopped`). */
  status: "complete" | "cut" | "failed" | "stopped";
  error_code: string | null;
  compacted: boolean;
  /**
   * `{proposal_id}` on a propose_thought result, `{sources}` on a search,
   * `{action_id}` on a connector call that waits for approval, `{failed}` on
   * a connector call that failed. Each tool message from this server also
   * holds the `summary` its tool line showed in the stream. `{stopped}` is a
   * tool call the user stopped before it finished (no summary), and
   * `{stopped_tools}` on a stopped answer names the calls the model was still
   * sending when it stopped, in order.
   */
  details: {
    proposal_id?: string;
    sources?: unknown;
    action_id?: string;
    failed?: boolean;
    summary?: string;
    stopped?: boolean;
    stopped_tools?: string[];
  } | null;
  created_at: string;
};

/** The sources a stored search result holds. */
export function storedSources(message: StoredMessage): Source[] {
  return toSources(message.details?.sources);
}

/** How full the context is. `estimated` is true until the next answer reports the count. */
export type ContextMeter = {
  tokens: number;
  estimated: boolean;
  context_length: number | null;
  /** The estimated share of the tokens that the offered tool definitions take. */
  tool_tokens?: number;
};

/** A connector that is on in a conversation. */
export type ConversationConnector = { id: string; name: string };

export type ConversationDetail = ConversationSummary & {
  last_prompt_tokens: number | null;
  held_proposal_id: string | null;
  context: ContextMeter;
  messages: StoredMessage[];
  /** Every proposal of the conversation, in position order, with each part's saved state. */
  proposals: unknown[];
  /**
   * The answer running in this conversation, if any: it answers the user
   * message at `after_position`. Follow it with `followTurn`.
   */
  turn?: RunningTurn | null;
  /** Every connector action of the conversation, for its card (none while connectors are off). */
  actions?: unknown[];
  /** The connectors that are on, by name (none while connectors are off). */
  connectors?: ConversationConnector[];
};

export type RunningTurn = { after_position: number };

/** The stored proposals, skipping any that does not fit. */
export function storedProposals(conversation: ConversationDetail): Proposal[] {
  return (conversation.proposals ?? [])
    .map(toProposal)
    .filter((proposal): proposal is Proposal => proposal !== null);
}

/** The stored actions, skipping any that does not fit. */
export function storedActions(conversation: ConversationDetail): Action[] {
  return (conversation.actions ?? [])
    .map(toAction)
    .filter((action): action is Action => action !== null);
}

export type ConversationList = {
  conversations: ConversationSummary[];
  archived: ConversationSummary[];
};

export type ConversationChange = {
  title?: string;
  archived?: boolean;
  provider_id?: string;
  model?: string;
  reasoning_effort?: string | null;
};

/**
 * A card as the user left it, and the parts it covers: one, or every part
 * after a merge. A status part sends only `parts`: the server ignores the
 * fields for it and marks the thought done.
 */
export type ConfirmRequest = {
  parts: number[];
  title?: string;
  summary?: string;
  tags?: string[];
  category?: string | null;
  /**
   * The card's date with the browser's zone, or null for no date. Left out, the
   * thought gets no date; a part with two date choices needs it. An addition
   * keeps its thought's date, so the server ignores it with "add".
   */
  when?: When | null;
  /**
   * "add" adds the card to the filed thought `add_to`, at the version
   * `based_on` the card shows (the server's `updated_at`, unchanged). Left
   * out, the card is filed as a new thought.
   */
  mode?: "new" | "add";
  add_to?: string;
  based_on?: string;
};

export type ConfirmOutcome = { saved: boolean; thought_id: string; message: string };

const BASE = "/api/conversations";

export function listConversations(): Promise<ConversationList> {
  return apiFetch<ConversationList>(BASE);
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return apiFetch<ConversationDetail>(`${BASE}/${encodeURIComponent(id)}`);
}

export function updateConversation(
  id: string,
  change: ConversationChange,
): Promise<ConversationDetail> {
  return apiFetch<ConversationDetail>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(change),
  });
}

/** Sets which connectors are on, from the next turn: the whole set, not a change. */
export function setConversationConnectors(
  id: string,
  connectorIds: string[],
): Promise<ConversationDetail> {
  return apiFetch<ConversationDetail>(`${BASE}/${encodeURIComponent(id)}/connectors`, {
    method: "PUT",
    body: JSON.stringify({ connector_ids: connectorIds }),
  });
}

export function deleteConversation(id: string): Promise<void> {
  return apiFetch<void>(`${BASE}/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** Saves one card of a proposal. Repeating the request answers the same thought. */
export function confirmProposal(
  id: string,
  proposalId: string,
  card: ConfirmRequest,
): Promise<ConfirmOutcome> {
  return apiFetch<ConfirmOutcome>(
    `${BASE}/${encodeURIComponent(id)}/proposals/${encodeURIComponent(proposalId)}/confirm`,
    { method: "POST", body: JSON.stringify(card) },
  );
}

/**
 * Approves or declines an action. A repeated approval answers the same
 * outcome; an expired action throws `action_expired`.
 */
export async function decideAction(
  id: string,
  actionId: string,
  decision: "approve" | "decline",
): Promise<Action> {
  const answer = await apiFetch<unknown>(
    `${BASE}/${encodeURIComponent(id)}/actions/${encodeURIComponent(actionId)}`,
    { method: "POST", body: JSON.stringify({ decision }) },
  );
  const action = toAction(answer);
  if (!action) throw new Error("The server's answer about the action could not be read.");
  return action;
}

/**
 * The held proposal to show before archive or /compact; the server asks the
 * model when none is held, with the browser's zone for its "today".
 */
export async function offerProposal(id: string): Promise<Proposal | null> {
  const offered = await apiFetch<{ proposal: unknown }>(
    `${BASE}/${encodeURIComponent(id)}/proposal`,
    { method: "POST", body: JSON.stringify({ time_zone: browserTimeZone() }) },
  );
  return toProposal(offered.proposal);
}

/** Stores an accepted /compact summary. The messages it replaces stay, marked compacted. */
export function acceptCompaction(
  id: string,
  summary: string,
  throughPosition: number,
): Promise<ConversationDetail> {
  return apiFetch<ConversationDetail>(`${BASE}/${encodeURIComponent(id)}/compaction`, {
    method: "POST",
    body: JSON.stringify({ summary, through_position: throughPosition }),
  });
}
