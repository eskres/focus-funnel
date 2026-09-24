// Deleting all of the user's data, then logging out.
import { apiFetch } from "@/lib/api";

export const deleteMyData = () => apiFetch<void>("/api/me", { method: "DELETE" });

/** /auth/logout is a route handler, not a page, so it needs a full browser navigation. */
export function logOut() {
  window.location.assign(new URL("/auth/logout", window.location.origin));
}
