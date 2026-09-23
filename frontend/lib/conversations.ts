// Typed client for the stored conversations (`/api/conversations`).
import { apiFetch } from "@/lib/api";
import type { Proposal } from "@/lib/sse";

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
  created_at: string;
};

export type HeldProposal = Proposal & { position: number };

export type ConversationDetail = ConversationSummary & {
  last_prompt_tokens: number | null;
  held_proposal: HeldProposal | null;
  messages: StoredMessage[];
};

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

export type ConfirmOutcome = { saved: boolean; message: string; proposal: Proposal };

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

export function confirmProposal(id: string, proposal: Proposal): Promise<ConfirmOutcome> {
  return apiFetch<ConfirmOutcome>(`${BASE}/${encodeURIComponent(id)}/proposal/confirm`, {
    method: "POST",
    body: JSON.stringify(proposal),
  });
}

/** The held proposal to show before archive or /compact; the server asks the model when none is held. */
export function offerProposal(id: string): Promise<{ held_proposal: HeldProposal | null }> {
  return apiFetch<{ held_proposal: HeldProposal | null }>(
    `${BASE}/${encodeURIComponent(id)}/proposal`,
    { method: "POST" },
  );
}
