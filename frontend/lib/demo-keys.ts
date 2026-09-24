// Demo mode: provider keys held by the visitor's browser in a sealed,
// HttpOnly cookie, never stored on the server. The API proxy drops keys past
// their idle time or maximum age, sends the rest to the backend in the
// X-Provider-Keys header, and re-seals the cookie with a fresh last use.

import type { DemoConfig } from "@/lib/auth-mode";
import { DEMO_KEYS_COOKIE, clearCookie, readCookies, seal, serializeCookie, unseal } from "@/lib/session";

export const PROVIDER_KEYS_HEADER = "X-Provider-Keys";

export interface HeldKeys {
  keys: Record<string, { key: string; set_at: number }>;
  /** Milliseconds since the epoch. */
  last_used_at: number;
}

const empty = (now: number): HeldKeys => ({ keys: {}, last_used_at: now });

const idleMs = (demo: DemoConfig) => demo.keyTtlMinutes * 60_000;
const maxMs = (demo: DemoConfig) => demo.keyMaxHours * 3_600_000;

/** When a held key is forgotten if the visitor makes no other request. */
export function keyExpiresAt(setAt: number, now: number, demo: DemoConfig): number {
  return Math.min(now + idleMs(demo), setAt + maxMs(demo));
}

/** The held keys still in time: a long idle drops all of them, age drops each. */
export function liveKeys(held: HeldKeys, now: number, demo: DemoConfig): HeldKeys {
  if (now - held.last_used_at > idleMs(demo)) return empty(now);
  const keys = Object.fromEntries(
    Object.entries(held.keys).filter(([, entry]) => now - entry.set_at <= maxMs(demo)),
  );
  return { keys, last_used_at: now };
}

export async function readHeldKeys(request: Request, secret: string): Promise<HeldKeys | null> {
  return unseal<HeldKeys>(readCookies(request).get(DEMO_KEYS_COOKIE), secret, "demo-keys");
}

/** The Set-Cookie header that stores the held keys, or clears the cookie when none are left. */
export async function heldKeysCookie(held: HeldKeys, secret: string, demo: DemoConfig) {
  if (Object.keys(held.keys).length === 0) return clearCookie(DEMO_KEYS_COOKIE);
  const maxAgeSeconds = Math.ceil(maxMs(demo) / 1000);
  const sealed = await seal(held, secret, "demo-keys", maxAgeSeconds);
  return serializeCookie(DEMO_KEYS_COOKIE, sealed, { maxAge: maxAgeSeconds });
}

/** The X-Provider-Keys header value: base64url JSON of {provider_id: {key, expires_at}}. */
export function providerKeysHeader(held: HeldKeys, now: number, demo: DemoConfig): string | null {
  const entries = Object.entries(held.keys);
  if (entries.length === 0) return null;
  const payload = Object.fromEntries(
    entries.map(([provider, entry]) => [
      provider,
      { key: entry.key, expires_at: new Date(keyExpiresAt(entry.set_at, now, demo)).toISOString() },
    ]),
  );
  return Buffer.from(JSON.stringify(payload)).toString("base64url");
}

export function withKey(held: HeldKeys, provider: string, key: string, now: number): HeldKeys {
  return { keys: { ...held.keys, [provider]: { key, set_at: now } }, last_used_at: now };
}

export function withoutKey(held: HeldKeys, provider: string, now: number): HeldKeys {
  const keys = { ...held.keys };
  delete keys[provider];
  return { keys, last_used_at: now };
}

export { empty as noHeldKeys };
