// Typed clients for one stored thought (`/api/thoughts`) and the categories
// setting (`/api/settings/categories`).
import { apiFetch } from "@/lib/api";
import type { When } from "@/lib/dates";

/** The conversation and proposal a thought was saved from, as they are now. */
export type ThoughtOrigin = {
  conversation_id: string;
  conversation_title: string;
  archived: boolean;
  proposal_id: string;
  proposed_at: string;
};

/**
 * One addition to the thought, from a later proposal: the conversation it came
 * from, as it is titled now, and the proposal whose card it was.
 */
export type ThoughtAddition = {
  id: string;
  added_at: string;
  undone: boolean;
  conversation_id: string;
  conversation_title: string;
  proposal_id: string;
};

export type Thought = {
  id: string;
  title: string;
  summary: string;
  tags: string[];
  category: string | null;
  raw_text: string | null;
  /** The thought's own date; null, or missing from an older server, when it has none. */
  when?: When | null;
  created_at: string;
  updated_at: string;
  /** Null, or missing from an older server, when there is no origin. */
  origin?: ThoughtOrigin | null;
  /** Newest first; missing from an older server. */
  additions?: ThoughtAddition[];
  /** Missing from an older server, which reads as open. */
  status?: ThoughtStatus;
  /** When the status last changed; null, or missing, when it never did. */
  status_changed_at?: string | null;
};

/** Whether the thought is still to do. */
export type ThoughtStatus = "open" | "done";

const thoughtPath = (id: string) => `/api/thoughts/${encodeURIComponent(id)}`;

export function getThought(id: string): Promise<Thought> {
  return apiFetch<Thought>(thoughtPath(id));
}

/**
 * The fields of a thought the user can change. Raw text is not one of them.
 * A `when` of null clears the date. A `status` change keeps the "changed" date.
 */
export type ThoughtChange = Partial<Pick<Thought, "title" | "summary" | "tags" | "category">> & {
  when?: When | null;
  status?: ThoughtStatus;
};

/**
 * Sent on window after a thought is changed or deleted in this page, so a
 * saved proposal card can follow it.
 */
export const THOUGHT_CHANGED_EVENT = "ff:thought-changed";

/** `undone` names the proposal whose addition was undone, so its card can say so. */
export type ThoughtChanged =
  | { id: string; title: string; undone?: string }
  | { id: string; deleted: true };

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

/** A dated thought on the Upcoming page. */
export type UpcomingItem = { id: string; title: string; category: string | null; when: When };

/** At most 200 items; `more` says that more exist. */
export type Upcoming = { items: UpcomingItem[]; more: boolean };

/**
 * The dated thoughts that end, or start when they have no end, on `from` or
 * later, in date order. `from` is the browser's local today, `YYYY-MM-DD`.
 */
export function getUpcoming(from: string): Promise<Upcoming> {
  return apiFetch<Upcoming>(`/api/thoughts/upcoming?from=${encodeURIComponent(from)}`);
}

/** Deletes the thought for good. */
export async function deleteThought(id: string): Promise<void> {
  await apiFetch<void>(thoughtPath(id), { method: "DELETE" });
  announce({ id, deleted: true });
}

/**
 * Undoes the thought's last addition and answers the thought as it is now.
 * Refused with `ThoughtChangedError` when the thought changed after it.
 */
export async function undoAddition(id: string, addition: ThoughtAddition): Promise<Thought> {
  const thought = await apiFetch<Thought>(
    `${thoughtPath(id)}/additions/${encodeURIComponent(addition.id)}/undo`,
    { method: "POST" },
  );
  announce({ id: thought.id, title: thought.title, undone: addition.proposal_id });
  return thought;
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
