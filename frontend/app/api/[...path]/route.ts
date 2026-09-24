import { getAuthConfig, getBackendCredential, type BackendCredential } from "@/lib/auth-mode";
import { PROVIDER_KEYS_HEADER } from "@/lib/demo-keys";
import { prepareDemoCall } from "@/lib/demo-proxy";

// Forwards every /api/... call to the private FastAPI backend with the user's
// credential for the auth mode: the ID token, renewed when it is about to
// expire, or the demo session value. The credential is read from a sealed
// cookie on the server and never sent to the browser. Response bodies are
// streamed through without buffering.

// Request headers passed on to the backend. Cookies (the session) and any
// client-sent Authorization header are deliberately not forwarded.
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

/** Adds Set-Cookie headers, such as a renewed session, to a response. */
function withCookies(response: Response, setCookies: string[]): Response {
  for (const cookie of setCookies) response.headers.append("set-cookie", cookie);
  return response;
}

async function getCredential(request: Request): Promise<BackendCredential> {
  try {
    return await getBackendCredential(request);
  } catch (error) {
    // Setup mistakes are server errors, not a logged-out user.
    console.error("API proxy: could not get a credential", errorDetails(error));
    return {
      response: errorResponse(500, "internal_error", "Something went wrong. Try again."),
    };
  }
}

/** Percent-decodes a segment, or returns null when it is not a valid encoding. */
function decodeOnce(segment: string): string | null {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

/**
 * Next.js hands over segments it has already percent-decoded, so the segment is
 * checked as it arrives. Decoding a second time is only defense in depth, for a
 * segment that still holds an encoded traversal sequence such as `%2e%2e`. A
 * segment that cannot be decoded is a literal string, such as `100%` from `100%25`
 * in the URL, and the as-arrived check already covers it. `backendTarget`
 * re-encodes whatever passes, so it reaches the backend as one path component.
 */
function isSafeSegment(segment: string): boolean {
  const values = [segment];
  const decoded = decodeOnce(segment);
  if (decoded !== null) values.push(decoded);
  return values.every(
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
  // Unreachable from this handler: `path` is the literal "/api/" followed by
  // encodeURIComponent-escaped segments, and a path-absolute reference cannot
  // resolve to another origin. Kept as defense in depth, so a later change to
  // how `path` is built cannot quietly send a request off the backend origin.
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

  const auth = await getCredential(request);
  if ("response" in auth) return auth.response;

  // Demo mode: held provider keys, and the end of a demo session.
  const config = getAuthConfig();
  const demoCall = config.mode === "demo" ? await prepareDemoCall(request, path, config) : null;
  if (demoCall?.response) return demoCall.response;

  const headers = new Headers({ Authorization: `Bearer ${auth.credential}` });
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  if (demoCall?.providerKeys) headers.set(PROVIDER_KEYS_HEADER, demoCall.providerKeys);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    redirect: "manual",
    cache: "no-store",
    signal: request.signal,
  };
  if (demoCall?.body !== undefined) {
    init.body = demoCall.body;
  } else if (hasBody) {
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
    return withCookies(
      errorResponse(502, "backend_unreachable", "The server could not be reached. Try again."),
      auth.setCookies,
    );
  }

  // `redirect: "manual"` returns a 3xx instead of following it, and `location`
  // is not forwarded, so a redirect would reach the browser with no target.
  // The API has no redirecting endpoint, so an upstream 3xx means the call did
  // not complete: report it as a failed backend call and log it on the server.
  if (upstream.status >= 300 && upstream.status < 400) {
    await upstream.body?.cancel();
    console.error("API proxy: backend returned a redirect", {
      method: request.method,
      path: target.pathname,
      status: upstream.status,
    });
    return withCookies(
      errorResponse(502, "backend_unreachable", "The server could not be reached. Try again."),
      auth.setCookies,
    );
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) responseHeaders.set(name, value);
  }
  responseHeaders.set("Cache-Control", "no-cache");
  responseHeaders.set("X-Accel-Buffering", "no");
  // A renewed session.
  for (const cookie of auth.setCookies) responseHeaders.append("set-cookie", cookie);

  if (demoCall) {
    // Nothing from a demo instance may be kept by a cache.
    responseHeaders.set("Cache-Control", "no-store");
    return demoCall.finish(upstream, responseHeaders);
  }

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
