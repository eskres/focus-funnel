import { connection } from "next/server";

import type { DemoSettings } from "@/components/demo/demo-context";
import { getAuthConfig } from "@/lib/auth-mode";

/**
 * The demo settings pages pass to the client, or null outside demo mode. Read
 * per request, so the mode comes from the running server, not the build.
 */
export async function demoSettings(): Promise<DemoSettings | null> {
  await connection();
  const { demo } = getAuthConfig();
  return demo ? { keyTtlMinutes: demo.keyTtlMinutes, keyMaxHours: demo.keyMaxHours } : null;
}
