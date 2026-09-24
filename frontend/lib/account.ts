// Deleting the user's content, usage history, or account.
import { apiFetch } from "@/lib/api";

/** Fired on `window` after the usage history is deleted, so the usage section loads again. */
export const USAGE_DELETED = "focus-funnel:usage-deleted";

export const deleteMyContent = () => apiFetch<void>("/api/me/content", { method: "DELETE" });

export const deleteMyUsage = () => apiFetch<void>("/api/me/usage", { method: "DELETE" });

export const deleteMyAccount = () => apiFetch<void>("/api/me", { method: "DELETE" });

/** /auth/logout is a route handler, not a page, so it needs a full browser navigation. */
export function logOut() {
  window.location.assign(new URL("/auth/logout", window.location.origin));
}
