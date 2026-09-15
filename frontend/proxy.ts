import { NextResponse, type NextRequest } from "next/server";

import { auth0 } from "@/lib/auth0";

// Pages anyone can open without logging in.
const PUBLIC_PATHS = new Set(["/"]);

export async function proxy(request: NextRequest) {
  // Mounts the SDK's /auth/* routes (login, logout, callback) and keeps rolling
  // sessions fresh on every other request.
  const authResponse = await auth0.middleware(request);

  const { pathname, search } = request.nextUrl;
  if (pathname.startsWith("/auth/") || PUBLIC_PATHS.has(pathname)) {
    return authResponse;
  }

  // API routes answer 401 `unauthenticated` themselves instead of redirecting,
  // so fetch calls get the shared error format.
  if (pathname.startsWith("/api/")) {
    return authResponse;
  }

  const session = await auth0.getSession(request);
  if (!session) {
    const loginUrl = new URL("/auth/login", request.nextUrl.origin);
    loginUrl.searchParams.set("returnTo", pathname + search);
    return NextResponse.redirect(loginUrl);
  }

  return authResponse;
}

export const config = {
  matcher: [
    // Every path except Next.js build assets and metadata files.
    "/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)",
  ],
};
