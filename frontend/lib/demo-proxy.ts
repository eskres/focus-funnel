// Demo mode in the API proxy: the held provider keys (design decision 8) and
// the end of a demo session.

import type { AuthConfig } from "@/lib/auth-mode";
import {
  heldKeysCookie,
  keyExpiresAt,
  liveKeys,
  noHeldKeys,
  providerKeysHeader,
  readHeldKeys,
  withKey,
  withoutKey,
  type HeldKeys,
} from "@/lib/demo-keys";
import { DEMO_KEYS_COOKIE, DEMO_SESSION_COOKIE, clearCookie } from "@/lib/session";

export interface DemoCall {
  /** An answer given here, without calling the backend. */
  response?: Response;
  /** The request body to send instead of the original stream (a key save). */
  body?: string;
  /** The X-Provider-Keys header value, when the visitor holds keys. */
  providerKeys: string | null;
  /** Builds the browser's response from the backend's. */
  finish: (upstream: Response, headers: Headers) => Promise<Response>;
}

/** The provider id of a /api/providers/{id}/key call, or null. */
function keyRoute(segments: string[]): string | null {
  return segments.length === 3 && segments[0] === "providers" && segments[2] === "key"
    ? segments[1]
    : null;
}

const endsSession = (segments: string[], method: string) =>
  method === "DELETE" && segments.join("/") === "demo/session";

const clearDemoCookies = () => [clearCookie(DEMO_SESSION_COOKIE), clearCookie(DEMO_KEYS_COOKIE)];

async function readErrorCode(text: string): Promise<string | null> {
  try {
    const body = JSON.parse(text) as { error?: { code?: unknown } };
    return typeof body.error?.code === "string" ? body.error.code : null;
  } catch {
    return null;
  }
}

export async function prepareDemoCall(
  request: Request,
  segments: string[],
  config: AuthConfig,
): Promise<DemoCall> {
  const demo = config.demo!;
  const secret = config.sessionSecret;
  const now = Date.now();
  const stored = await readHeldKeys(request, secret);
  let held: HeldKeys | null = stored ? liveKeys(stored, now, demo) : null;
  const provider = keyRoute(segments);
  const cookies: string[] = [];

  // "Forget key": only the cookie changes; the backend never had the key.
  if (provider !== null && request.method === "DELETE") {
    held = withoutKey(held ?? noHeldKeys(now), provider, now);
    const headers = new Headers({ "Cache-Control": "no-store" });
    headers.append("set-cookie", await heldKeysCookie(held, secret, demo));
    return {
      response: new Response(null, { status: 204, headers }),
      providerKeys: null,
      finish: async (upstream) => upstream,
    };
  }

  // A key save: the key is in the body once, and in the cookie afterwards.
  let body: string | undefined;
  let savedKey: string | null = null;
  if (provider !== null && request.method === "PUT") {
    body = await request.text();
    try {
      const parsed = JSON.parse(body) as { key?: unknown };
      savedKey = typeof parsed.key === "string" && parsed.key.trim() ? parsed.key.trim() : null;
    } catch {
      savedKey = null;
    }
  }

  return {
    body,
    providerKeys: held ? providerKeysHeader(held, now, demo) : null,
    finish: async (upstream, headers) => {
      let responseBody: BodyInit | null = upstream.body;

      if (savedKey !== null && provider !== null && upstream.ok) {
        held = withKey(held ?? noHeldKeys(now), provider, savedKey, now);
        const status = (await upstream.json()) as Record<string, unknown>;
        status.key_expires_at = new Date(keyExpiresAt(now, now, demo)).toISOString();
        responseBody = JSON.stringify(status);
        headers.set("content-type", "application/json");
      } else if (upstream.status === 401) {
        const text = await upstream.text();
        if ((await readErrorCode(text)) === "demo_session_expired") {
          // The backend has deleted, or will delete, everything of this session.
          cookies.push(...clearDemoCookies());
          held = null;
        }
        responseBody = text;
      } else if (endsSession(segments, request.method) && upstream.ok) {
        cookies.push(...clearDemoCookies());
        held = null;
      }

      if (held !== null) cookies.push(await heldKeysCookie(held, secret, demo));
      for (const cookie of cookies) headers.append("set-cookie", cookie);
      return new Response(responseBody, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers,
      });
    },
  };
}
