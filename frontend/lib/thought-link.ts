// The open thought lives in the address as `?thought=<id>`, so it can be
// copied and Back closes it. The address changes with history.pushState,
// which Next.js keeps in step with its router, so the chat stays mounted with
// its scroll position and the composer's text.
//
// A thought's origin opens its conversation at the proposal card, as
// `/app/<conversation>?proposal=<id>`. In the conversation already open, the
// address changes the same way, for the same reason.
import { useMemo, useSyncExternalStore } from "react";

export const THOUGHT_PARAM = "thought";
export const PROPOSAL_PARAM = "proposal";
const CHANGE = "ff:thought-change";
// Counts origin clicks in this page, so a click on the proposal the address
// already names still scrolls to it.
let anchorRequests = 0;

/** The address of the current page with a thought open. */
export function thoughtHref(id: string): string {
  const url = new URL(window.location.href);
  url.searchParams.set(THOUGHT_PARAM, id);
  return url.pathname + url.search;
}

function go(url: URL) {
  window.history.pushState(null, "", url.pathname + url.search + url.hash);
  window.dispatchEvent(new Event(CHANGE));
}

export function openThought(id: string) {
  go(new URL(thoughtHref(id), window.location.href));
}

export function closeThought() {
  const url = new URL(window.location.href);
  url.searchParams.delete(THOUGHT_PARAM);
  go(url);
}

/** The address of a conversation opened at one proposal card. */
export function originHref(conversationId: string, proposalId: string): string {
  return `/app/${encodeURIComponent(conversationId)}?${PROPOSAL_PARAM}=${encodeURIComponent(proposalId)}`;
}

/** Whether the conversation is the one this page shows. */
export function isOpenConversation(conversationId: string): boolean {
  return window.location.pathname === `/app/${encodeURIComponent(conversationId)}`;
}

/**
 * Open the conversation at the proposal card in this page, which closes the
 * thought. Only for the open conversation: another one needs `router.push`.
 */
export function openOriginHere(conversationId: string, proposalId: string) {
  anchorRequests += 1;
  go(new URL(originHref(conversationId, proposalId), window.location.href));
}

function subscribe(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  window.addEventListener(CHANGE, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(CHANGE, onChange);
  };
}

/** The id of the open thought, or null. */
export function useOpenThought(): string | null {
  return useSyncExternalStore(
    subscribe,
    () => new URLSearchParams(window.location.search).get(THOUGHT_PARAM),
    () => null,
  );
}

export type ProposalAnchor = {
  /** The proposal the address names, or null. */
  id: string | null;
  /** Changes on each origin click, even for the same proposal. */
  request: number;
};

/** The proposal card the address names (`?proposal=<id>`). */
export function useProposalAnchor(): ProposalAnchor {
  const snapshot = useSyncExternalStore(
    subscribe,
    () => `${anchorRequests}:${new URLSearchParams(window.location.search).get(PROPOSAL_PARAM) ?? ""}`,
    () => "0:",
  );
  return useMemo(() => {
    const colon = snapshot.indexOf(":");
    return { id: snapshot.slice(colon + 1) || null, request: Number(snapshot.slice(0, colon)) };
  }, [snapshot]);
}
