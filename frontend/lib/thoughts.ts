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

export function getThought(id: string): Promise<Thought> {
  return apiFetch<Thought>(`/api/thoughts/${encodeURIComponent(id)}`);
}

/** The five fixed kinds, and the ones the user added. */
export type Categories = { fixed: string[]; added: string[] };

export const FIXED_CATEGORIES = ["task", "idea", "decision", "note", "reference"];

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
