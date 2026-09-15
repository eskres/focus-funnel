import { AccessTokenError } from "@auth0/nextjs-auth0/errors";

import { auth0 } from "@/lib/auth0";

// Forwards every /api/... call to the private FastAPI backend with the user's
// Auth0 access token. The token is read on the server and never sent to the
// browser. Response bodies are streamed through without buffering.

// Request headers passed on to the backend. Cookies (the Auth0 session) and
// any client-sent Authorization header are deliberately not forwarded.
const FORWARDED_REQUEST_HEADERS = ["accept", "accept-language", "content-type"];

// Response headers passed back to the browser. Everything else (Set-Cookie,
// WWW-Authenticate, Server, hop-by-hop and encoding headers) is dropped.
const FORWARDED_RESPONSE_HEADERS = [
  "content-disposition",
  "content-language",
  "content-type",
  "etag",
  "last-modified",
  "retry-after",
];

type ProxyContext = RouteContext<"/api/[...path]">;

function errorResponse(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status });
}

function errorDetails(error: unknown) {
  return error instanceof Error
    ? { name: error.name, message: error.message }
    : { message: String(error) };
}

type TokenResult = { token: string } | { response: Response };

async function getAccessToken(): Promise<TokenResult> {
  const unauthenticated = {
    response: errorResponse(401, "unauthenticated", "Log in to continue."),
  };
  try {
    const session = await auth0.getSession();
    if (!session) return unauthenticated;
    const { token } = await auth0.getAccessToken();
    return { token };
  } catch (error) {
    // Missing or expired session, or a refresh token that no longer works.
    if (error instanceof AccessTokenError) return unauthenticated;
    // Setup mistakes or Auth0 outages are server errors, not a logged-out user.
    console.error("API proxy: could not get an access token", errorDetails(error));
    return {
      response: errorResponse(500, "internal_error", "Something went wrong. Try again."),
    };
  }
}

function isSafeSegment(segment: string): boolean {
  let decoded: string;
  try {
    decoded = decodeURIComponent(segment);
  } catch {
    return false;
  }
  return [segment, decoded].every(
    (value) =>
      value !== "" &&
      value !== "." &&
      value !== ".." &&
      !value.includes("/") &&
      !value.includes("\\"),
  );
}

/** Builds the backend URL from the route segments, or returns null if unsafe. */
function backendTarget(backendUrl: string, segments: string[], search: string): URL | null {
  if (segments.length === 0 || !segments.every(isSafeSegment)) return null;
  const base = new URL(backendUrl);
  const path = `/api/${segments.map(encodeURIComponent).join("/")}`;
  const target = new URL(path + search, base.origin);
  if (target.origin !== base.origin || !target.pathname.startsWith("/api/")) {
    return null;
  }
  return target;
}

async function forward(request: Request, context: ProxyContext): Promise<Response> {
  const backendUrl = process.env.BACKEND_URL;
  if (!backendUrl) {
    console.error("API proxy: BACKEND_URL is not set");
    return errorResponse(500, "internal_error", "Something went wrong. Try again.");
  }

  const { path } = await context.params;
  const target = backendTarget(backendUrl, path, new URL(request.url).search);
  if (!target) {
    return errorResponse(404, "not_found", "Not found.");
  }

  const auth = await getAccessToken();
  if ("response" in auth) return auth.response;

  const headers = new Headers({ Authorization: `Bearer ${auth.token}` });
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    redirect: "manual",
    cache: "no-store",
    signal: request.signal,
  };
  if (hasBody) {
    init.body = request.body;
    // Required by Node's fetch to send a streamed request body.
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (error) {
    console.error("API proxy: backend request failed", {
      method: request.method,
      path: target.pathname,
      ...errorDetails(error),
    });
    return errorResponse(
      502,
      "backend_unreachable",
      "The server could not be reached. Try again.",
    );
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) responseHeaders.set(name, value);
  }
  responseHeaders.set("Cache-Control", "no-cache");
  responseHeaders.set("X-Accel-Buffering", "no");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
