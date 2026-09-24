import { NextResponse, type NextRequest } from "next/server";

import { getAuthConfig, type AuthConfig, type DemoConfig } from "@/lib/auth-mode";
import { RateLimiter, clientAddress } from "@/lib/rate-limit";
import { DEMO_SESSION_COOKIE, readCookies, readSession, serializeCookie } from "@/lib/session";

// Where logged-in users (and demo visitors) go instead of the landing page.
const LOGGED_IN_HOME = "/app";

/** Pages anyone can open without logging in, per mode. */
function isPublicPage(config: AuthConfig, pathname: string): boolean {
  if (pathname === "/") return true;
  return config.mode === "firebase" && pathname === "/login";
}

/** Where a logged-out user goes to log in, keeping the page they asked for. */
export function loginUrl(config: AuthConfig, origin: string, returnTo: string): URL {
  const url = new URL(config.mode === "firebase" ? "/login" : "/auth/login", origin);
  url.searchParams.set("returnTo", returnTo);
  return url;
}

export async function proxy(request: NextRequest) {
  let config: AuthConfig;
  try {
    config = getAuthConfig();
  } catch (error) {
    console.error("Auth settings are not valid", error instanceof Error ? error.message : error);
    return new NextResponse("The server is not configured correctly.", { status: 500 });
  }

  const { pathname, search } = request.nextUrl;

  if (config.mode === "demo") return noStore(await demoRequest(request, config.demo!));

  // Login routes and pages run on their own. API routes answer 401
  // `unauthenticated` themselves instead of redirecting, so fetch calls get
  // the shared error format.
  if (pathname.startsWith("/auth/") || pathname.startsWith("/api/")) {
    return NextResponse.next();
  }

  const session = await readSession(request, config.sessionSecret);
  const loggedIn = session !== null && session.mode === config.mode;

  if (isPublicPage(config, pathname)) {
    if (!loggedIn) return NextResponse.next();
    return NextResponse.redirect(new URL(LOGGED_IN_HOME, request.nextUrl.origin));
  }

  if (!loggedIn) {
    return NextResponse.redirect(loginUrl(config, request.nextUrl.origin, pathname + search));
  }
  return NextResponse.next();
}

// --- Demo mode ------------------------------------------------------------------

const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;
let limits: { key: string; requests: RateLimiter; sessions: RateLimiter } | null = null;

/** The limiters for these settings, kept for the life of the process. */
function demoLimits(demo: DemoConfig) {
  const key = `${demo.rateLimit}/${demo.newSessionsPerHour}`;
  if (limits?.key !== key) {
    limits = {
      key,
      requests: new RateLimiter(demo.rateLimit, MINUTE_MS),
      sessions: new RateLimiter(demo.newSessionsPerHour, HOUR_MS),
    };
  }
  return limits;
}

/** Forgets every limiter's state (tests start each case fresh). */
export function resetDemoLimits() {
  limits = null;
}

/** Nothing from a demo instance may be kept by a browser or proxy cache. */
function noStore(response: NextResponse): NextResponse {
  response.headers.set("Cache-Control", "no-store");
  return response;
}

function rateLimited(request: NextRequest, retryAfterSeconds: number): NextResponse {
  const message = `Too many requests. Try again in ${retryAfterSeconds} seconds.`;
  const headers = { "Retry-After": String(retryAfterSeconds) };
  if (request.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.json({ error: { code: "rate_limited", message } }, { status: 429, headers });
  }
  return new NextResponse(message, { status: 429, headers: { ...headers, "Content-Type": "text/plain" } });
}

/** Demo mode: a per-address rate limit on every request, and no login. */
async function demoRequest(request: NextRequest, demo: DemoConfig): Promise<NextResponse> {
  const address = clientAddress(request, demo.trustedProxy);
  const { requests, sessions } = demoLimits(demo);
  const take = requests.take(address);
  if (!take.allowed) return rateLimited(request, take.retryAfterSeconds);

  const { pathname } = request.nextUrl;
  if (pathname.startsWith("/auth/") || pathname.startsWith("/api/")) return NextResponse.next();
  return demoPage(request, () => sessions.take(address));
}

/** A page request without a session starts one. */
async function demoPage(
  request: NextRequest,
  takeSession: () => ReturnType<RateLimiter["take"]>,
): Promise<NextResponse> {
  const { pathname, origin } = request.nextUrl;
  if (pathname.startsWith("/demo/")) return NextResponse.next();

  if (readCookies(request).has(DEMO_SESSION_COOKIE)) {
    return pathname === "/"
      ? NextResponse.redirect(new URL(LOGGED_IN_HOME, origin))
      : NextResponse.next();
  }

  const allowed = takeSession();
  if (!allowed.allowed) {
    const url = new URL("/demo/unavailable", origin);
    url.searchParams.set("reason", "limit");
    const refused = NextResponse.rewrite(url, { status: 429 });
    refused.headers.set("Retry-After", String(allowed.retryAfterSeconds));
    return refused;
  }

  const started = await startDemoSession();
  if ("unavailable" in started) {
    const url = new URL("/demo/unavailable", origin);
    url.searchParams.set("reason", started.unavailable);
    return NextResponse.rewrite(url, { status: started.unavailable === "full" ? 503 : 502 });
  }

  const cookie = serializeCookie(DEMO_SESSION_COOKIE, started.session, {
    maxAge: (Date.parse(started.expiresAt) - Date.now()) / 1000,
  });
  if (pathname === "/") {
    const redirect = NextResponse.redirect(new URL(LOGGED_IN_HOME, origin));
    redirect.headers.append("set-cookie", cookie);
    return redirect;
  }
  // The page itself already sees the new session.
  const headers = new Headers(request.headers);
  const existing = headers.get("cookie");
  const pair = `${DEMO_SESSION_COOKIE}=${encodeURIComponent(started.session)}`;
  headers.set("cookie", existing ? `${existing}; ${pair}` : pair);
  const response = NextResponse.next({ request: { headers } });
  response.headers.append("set-cookie", cookie);
  return response;
}

type DemoStart = { session: string; expiresAt: string } | { unavailable: "full" | "error" };

async function startDemoSession(): Promise<DemoStart> {
  const backendUrl = process.env.BACKEND_URL;
  if (!backendUrl) {
    console.error("Demo: BACKEND_URL is not set");
    return { unavailable: "error" };
  }
  try {
    const response = await fetch(new URL("/api/demo/sessions", backendUrl), {
      method: "POST",
      cache: "no-store",
    });
    if (response.status === 503) {
      const body = (await response.json().catch(() => null)) as { error?: { code?: string } } | null;
      if (body?.error?.code === "demo_full") return { unavailable: "full" };
    }
    if (!response.ok) {
      console.error("Demo: the backend refused to start a session", { status: response.status });
      return { unavailable: "error" };
    }
    const body = (await response.json()) as { session: string; expires_at: string };
    return { session: body.session, expiresAt: body.expires_at };
  } catch (error) {
    console.error("Demo: could not reach the backend", error instanceof Error ? error.message : error);
    return { unavailable: "error" };
  }
}

export const config = {
  matcher: [
    // Every path except Next.js build assets and metadata files.
    "/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)",
  ],
};
