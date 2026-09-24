// Sealed, HttpOnly cookies that hold the login session and other server-only
// state. Values are encrypted with jose (`dir` + `A256GCM`) under a key derived
// from SESSION_SECRET, so the browser can neither read nor change them. Nothing
// is stored on the server.

import { hkdfSync } from "node:crypto";

import { CompactEncrypt, compactDecrypt } from "jose";

export const SESSION_COOKIE = "ff_session";
// Demo mode: the anonymous session value, and the held provider keys.
export const DEMO_SESSION_COOKIE = "ff_demo";
export const DEMO_KEYS_COOKIE = "ff_demo_keys";
// Browsers cap a cookie near 4 KB; leave room for the name and attributes.
export const MAX_COOKIE_VALUE_BYTES = 3800;

/** What a sealed cookie is for. Each purpose gets its own key, so one cannot stand in for another. */
export type SealPurpose = "session" | "login" | "demo-keys";

export interface Session {
  mode: "oidc" | "firebase";
  idToken: string;
  refreshToken: string | null;
  /** When the ID token expires, in seconds since the epoch. */
  expiresAt: number;
}

export interface CookieOptions {
  maxAge?: number;
  path?: string;
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function keyFor(secret: string, purpose: SealPurpose): Uint8Array {
  return new Uint8Array(hkdfSync("sha256", secret, "focus-funnel", `ff-cookie:${purpose}`, 32));
}

/** Encrypts a JSON value. It is refused after `maxAgeSeconds`. */
export async function seal(
  value: unknown,
  secret: string,
  purpose: SealPurpose,
  maxAgeSeconds: number,
): Promise<string> {
  const payload = { v: value, exp: Math.floor(Date.now() / 1000) + maxAgeSeconds };
  return new CompactEncrypt(encoder.encode(JSON.stringify(payload)))
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .encrypt(keyFor(secret, purpose));
}

/** Decrypts a sealed value, or returns null when it is tampered with, expired, or for another purpose. */
export async function unseal<T>(
  sealed: string | undefined | null,
  secret: string,
  purpose: SealPurpose,
): Promise<T | null> {
  if (!sealed) return null;
  try {
    const { plaintext } = await compactDecrypt(sealed, keyFor(secret, purpose), {
      keyManagementAlgorithms: ["dir"],
      contentEncryptionAlgorithms: ["A256GCM"],
    });
    const payload = JSON.parse(decoder.decode(plaintext)) as { v: T; exp: number };
    if (typeof payload.exp !== "number" || payload.exp <= Date.now() / 1000) return null;
    return payload.v;
  } catch {
    return null;
  }
}

// --- Cookie headers ------------------------------------------------------------

/** Reads the Cookie header of a request into a map. */
export function readCookies(request: Request): Map<string, string> {
  const cookies = new Map<string, string>();
  for (const part of (request.headers.get("cookie") ?? "").split(";")) {
    const index = part.indexOf("=");
    if (index <= 0) continue;
    const name = part.slice(0, index).trim();
    const raw = part.slice(index + 1).trim();
    let value = raw;
    try {
      value = decodeURIComponent(raw);
    } catch {
      // Keep the raw value.
    }
    if (!cookies.has(name)) cookies.set(name, value);
  }
  return cookies;
}

/** A Set-Cookie header value: always HttpOnly, Secure, and SameSite=Lax. */
export function serializeCookie(name: string, value: string, options: CookieOptions = {}): string {
  const parts = [`${name}=${encodeURIComponent(value)}`, `Path=${options.path ?? "/"}`];
  if (options.maxAge !== undefined) parts.push(`Max-Age=${Math.max(0, Math.floor(options.maxAge))}`);
  parts.push("HttpOnly", "Secure", "SameSite=Lax");
  return parts.join("; ");
}

export function clearCookie(name: string, path = "/"): string {
  return serializeCookie(name, "", { maxAge: 0, path });
}

// --- Chunked cookies -------------------------------------------------------------

const chunkName = (name: string, index: number) => `${name}.${index}`;

/** The names a (possibly chunked) cookie has in this request. */
function presentNames(cookies: Map<string, string>, name: string): string[] {
  return [...cookies.keys()].filter((key) => key === name || key.startsWith(`${name}.`));
}

/** Reads a cookie that may be split into numbered chunks. */
export function readChunked(cookies: Map<string, string>, name: string): string | null {
  const whole = cookies.get(name);
  if (whole) return whole;
  const chunks: string[] = [];
  for (let index = 0; cookies.has(chunkName(name, index)); index++) {
    chunks.push(cookies.get(chunkName(name, index))!);
  }
  return chunks.length > 0 ? chunks.join("") : null;
}

/**
 * Set-Cookie headers that store a value, split into numbered chunks when it
 * would pass MAX_COOKIE_VALUE_BYTES, and clear the parts of an older value.
 */
export function writeChunked(
  cookies: Map<string, string>,
  name: string,
  value: string,
  options: CookieOptions,
): string[] {
  const headers: string[] = [];
  const written = new Set<string>();
  if (value.length <= MAX_COOKIE_VALUE_BYTES) {
    headers.push(serializeCookie(name, value, options));
    written.add(name);
  } else {
    for (let index = 0; index * MAX_COOKIE_VALUE_BYTES < value.length; index++) {
      const part = value.slice(index * MAX_COOKIE_VALUE_BYTES, (index + 1) * MAX_COOKIE_VALUE_BYTES);
      headers.push(serializeCookie(chunkName(name, index), part, options));
      written.add(chunkName(name, index));
    }
  }
  for (const stale of presentNames(cookies, name)) {
    if (!written.has(stale)) headers.push(clearCookie(stale));
  }
  return headers;
}

/** Set-Cookie headers that remove every part of a (possibly chunked) cookie. */
export function clearChunked(cookies: Map<string, string>, name: string): string[] {
  const names = new Set([name, ...presentNames(cookies, name)]);
  return [...names].map((present) => clearCookie(present));
}

// --- The login session -----------------------------------------------------------

// The cookie outlives the ID token: the refresh token renews it. A session
// that goes unused this long ends.
export const SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

export async function readSession(request: Request, secret: string): Promise<Session | null> {
  const sealed = readChunked(readCookies(request), SESSION_COOKIE);
  return unseal<Session>(sealed, secret, "session");
}

/** Set-Cookie headers that start or replace the session. */
export async function sessionCookies(
  request: Request,
  session: Session,
  secret: string,
): Promise<string[]> {
  const sealed = await seal(session, secret, "session", SESSION_MAX_AGE_SECONDS);
  return writeChunked(readCookies(request), SESSION_COOKIE, sealed, {
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
}

export function clearSessionCookies(request: Request): string[] {
  return clearChunked(readCookies(request), SESSION_COOKIE);
}
