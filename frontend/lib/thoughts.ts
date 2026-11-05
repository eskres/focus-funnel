// Typed clients for one stored thought (`/api/thoughts`) and the categories
// setting (`/api/settings/categories`).
import { apiFetch } from "@/lib/api";

/** The conversation and proposal a thought was saved from, as they are now. */
export type ThoughtOrigin = {
  conversation_id: string;
  conversation_title: string;
  archived: boolean;
  proposal_id: string;
  proposed_at: string;
};

export type Thought = {
  id: string;
  title: string;
  summary: string;
  tags: string[];
  category: string | null;
  raw_text: string | null;
  created_at: string;
  updated_at: string;
  /** Null, or missing from an older server, when there is no origin. */
  origin?: ThoughtOrigin | null;
};

const thoughtPath = (id: string) => `/api/thoughts/${encodeURIComponent(id)}`;

export function getThought(id: string): Promise<Thought> {
  return apiFetch<Thought>(thoughtPath(id));
}

/** The fields of a thought the user can change. Raw text is not one of them. */
export type ThoughtChange = Partial<Pick<Thought, "title" | "summary" | "tags" | "category">>;

/**
 * Sent on window after a thought is changed or deleted in this page, so a
 * saved proposal card can follow it.
 */
export const THOUGHT_CHANGED_EVENT = "ff:thought-changed";

export type ThoughtChanged = { id: string; title: string } | { id: string; deleted: true };

function announce(detail: ThoughtChanged) {
  window.dispatchEvent(new CustomEvent<ThoughtChanged>(THOUGHT_CHANGED_EVENT, { detail }));
}

/** Changes only the fields given, and answers the thought as it is now. */
export async function updateThought(id: string, fields: ThoughtChange): Promise<Thought> {
  const thought = await apiFetch<Thought>(thoughtPath(id), {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
  announce({ id: thought.id, title: thought.title });
  return thought;
}

/** Deletes the thought for good. */
export async function deleteThought(id: string): Promise<void> {
  await apiFetch<void>(thoughtPath(id), { method: "DELETE" });
  announce({ id, deleted: true });
}

/** The six fixed kinds, and the ones the user added. */
export type Categories = { fixed: string[]; added: string[] };

export const FIXED_CATEGORIES = ["task", "idea", "decision", "note", "reference", "event"];

const CATEGORIES = "/api/settings/categories";

export function getCategories(): Promise<Categories> {
  return apiFetch<Categories>(CATEGORIES);
}

export function addCategory(name: string): Promise<Categories> {
  return apiFetch<Categories>(CATEGORIES, { method: "POST", body: JSON.stringify({ name }) });
}

export function removeCategory(name: string): Promise<void> {
  return apiFetch<void>(`${CATEGORIES}/${encodeURIComponent(name)}`, { method: "DELETE" });
}
