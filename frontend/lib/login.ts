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

/** A same-site path to return to after login; anything else becomes /app. */
export function safeReturnTo(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return DEFAULT_RETURN_TO;
  }
  return value;
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
