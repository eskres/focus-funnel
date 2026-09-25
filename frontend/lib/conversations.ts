// Typed client for the stored conversations (`/api/conversations`).
import { apiFetch } from "@/lib/api";
import { toProposal, toSources, type Proposal, type Source } from "@/lib/sse";

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
  status: "complete" | "cut" | "failed";
  error_code: string | null;
  compacted: boolean;
  /** `{proposal_id}` on a propose_thought result, `{sources}` on a search. */
  details: { proposal_id?: string; sources?: unknown } | null;
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
};

export type ConversationDetail = ConversationSummary & {
  last_prompt_tokens: number | null;
  held_proposal_id: string | null;
  context: ContextMeter;
  messages: StoredMessage[];
  /** Every proposal of the conversation, in position order, with each part's saved state. */
  proposals: unknown[];
};

/** The stored proposals, skipping any that does not fit. */
export function storedProposals(conversation: ConversationDetail): Proposal[] {
  return (conversation.proposals ?? [])
    .map(toProposal)
    .filter((proposal): proposal is Proposal => proposal !== null);
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

/** A card as the user left it, and the parts it covers: one, or every part after a merge. */
export type ConfirmRequest = {
  parts: number[];
  title: string;
  summary: string;
  tags: string[];
  category: string | null;
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

/** The held proposal to show before archive or /compact; the server asks the model when none is held. */
export async function offerProposal(id: string): Promise<Proposal | null> {
  const offered = await apiFetch<{ proposal: unknown }>(
    `${BASE}/${encodeURIComponent(id)}/proposal`,
    { method: "POST" },
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
