import { NextResponse, type NextRequest } from "next/server";

import { getAuthConfig, type AuthConfig } from "@/lib/auth-mode";
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

  // Login routes and pages run on their own. API routes answer 401
  // `unauthenticated` themselves instead of redirecting, so fetch calls get
  // the shared error format.
  if (pathname.startsWith("/auth/") || pathname.startsWith("/api/")) {
    return NextResponse.next();
  }

  if (config.mode === "demo") return demoPage(request);

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

/** Demo mode has no login: a page request without a session starts one. */
async function demoPage(request: NextRequest): Promise<NextResponse> {
  const { pathname, origin } = request.nextUrl;
  if (pathname.startsWith("/demo/")) return NextResponse.next();

  if (readCookies(request).has(DEMO_SESSION_COOKIE)) {
    return pathname === "/"
      ? NextResponse.redirect(new URL(LOGGED_IN_HOME, origin))
      : NextResponse.next();
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
