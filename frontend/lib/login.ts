// Shared pieces of the login routes.

import type { AuthConfig } from "@/lib/auth-mode";

export const LOGIN_COOKIE = "ff_login";
// The login must finish within this time.
export const LOGIN_MAX_AGE_SECONDS = 10 * 60;
export const DEFAULT_RETURN_TO = "/app";

/** What the callback needs to finish the login that /auth/login starts. */
export interface LoginState {
  codeVerifier: string;
  state: string;
  nonce: string;
  returnTo: string;
}

// A stand-in origin for resolving a return path the way a browser would.
const PLACEHOLDER_ORIGIN = "http://placeholder.invalid";
// Route groups that are never a page to land on after login.
const NOT_A_PAGE = new Set(["api", "auth"]);

/**
 * A same-site page to return to after login; anything else becomes /app.
 *
 * The value is resolved with the WHATWG URL parser, as the router and the
 * redirects resolve it, and the resolved path is checked and returned. So dot
 * segments (`/settings/../api`, `%2e`), a dropped tab or line break, and a
 * backslash cannot lead to an API or auth route or to another site (thought-export
 * design decision 14).
 */
export function safeReturnTo(value: string | null | undefined): string {
  if (!value || !value.startsWith("/")) return DEFAULT_RETURN_TO;
  let parsed: URL;
  try {
    parsed = new URL(value, PLACEHOLDER_ORIGIN);
  } catch {
    return DEFAULT_RETURN_TO;
  }
  if (parsed.origin !== PLACEHOLDER_ORIGIN) return DEFAULT_RETURN_TO;
  const [, first = ""] = parsed.pathname.split("/");
  let segment: string;
  try {
    segment = decodeURIComponent(first);
  } catch {
    return DEFAULT_RETURN_TO;
  }
  if (NOT_A_PAGE.has(segment)) return DEFAULT_RETURN_TO;
  return parsed.pathname + parsed.search + parsed.hash;
}

/** The public base URL of the app: APP_BASE_URL, or the request's own origin. */
export function baseUrl(config: AuthConfig, request: Request): string {
  return config.appBaseUrl ?? new URL(request.url).origin;
}

/** A redirect that sets the given cookies. */
export function redirectWithCookies(url: string | URL, setCookies: string[] = []): Response {
  const headers = new Headers({ Location: url.toString(), "Cache-Control": "no-store" });
  for (const cookie of setCookies) headers.append("set-cookie", cookie);
  return new Response(null, { status: 303, headers });
}

export const loginFailedUrl = (base: string) => new URL("/auth/error", base);
export const notAllowedUrl = (base: string) => new URL("/auth/not-allowed", base);
