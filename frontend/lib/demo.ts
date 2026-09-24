// Typed client for the demo session routes.
import { apiFetch } from "@/lib/api";

export type DemoMe = {
  id: string;
  mode?: "demo";
  expires_at?: string;
  demo_notice_accepted?: boolean;
};

export const getMe = () => apiFetch<DemoMe>("/api/me");
export const acceptDemoNotice = () => apiFetch<void>("/api/demo/notice", { method: "POST" });
export const endDemo = () => apiFetch<void>("/api/demo/session", { method: "DELETE" });

/** A time a visitor can read, such as "Thu 25 Sep, 14:05". */
export function formatWhen(iso: string | undefined | null): string {
  if (!iso) return "an unknown time";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? "an unknown time"
    : date.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
