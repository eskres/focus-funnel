// The open thought lives in the address as `?thought=<id>`, so it can be
// copied and Back closes it. The address changes with history.pushState,
// which Next.js keeps in step with its router, so the chat stays mounted with
// its scroll position and the composer's text.
import { useSyncExternalStore } from "react";

export const THOUGHT_PARAM = "thought";
const CHANGE = "ff:thought-change";

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
