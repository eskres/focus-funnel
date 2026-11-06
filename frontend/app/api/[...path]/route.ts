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

// The setup token goes only to the backend's setup routes, never through the
// list above, so no other route (or anything that logs its headers) gets it.
const SETUP_TOKEN_HEADER = "x-setup-token";

// Response headers passed back to the browser. Everything else (Set-Cookie,
// WWW-Authenticate, Server, hop-by-hop and encoding headers) is dropped.
// `x-conversation-id` names the conversation a refused message was stored in
// (the caller's own id), so the chat can send to it again.
const FORWARDED_RESPONSE_HEADERS = [
  "content-disposition",
  "content-language",
  "content-type",
  "etag",
  "last-modified",
  "retry-after",
  "x-conversation-id",
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

/** `GET /api/me/export`, matched on the decoded route segments. */
function isExport(path: string[]): boolean {
  return path.length === 2 && path[0] === "me" && path[1] === "export";
}

/**
 * True unless the browser says another site started the request. `none` is a
 * navigation the user started; a request without the header (an older browser,
 * or curl) passes, since no current browser can be made to omit it.
 */
function fromThisSite(request: Request): boolean {
  const site = request.headers.get("sec-fetch-site");
  return site === null || site === "same-origin" || site === "none";
}

async function forward(request: Request, context: ProxyContext): Promise<Response> {
  const backendUrl = process.env.BACKEND_URL;
  if (!backendUrl) {
    console.error("API proxy: BACKEND_URL is not set");
    return errorResponse(500, "internal_error", "Something went wrong. Try again.");
  }

  const { path } = await context.params;
  // Only the app's own page may start an export (another site could otherwise
  // open it with the user's cookie and save their whole store). The check reads
  // the decoded segments, not the URL, so `%65`-style encodings cannot pass it.
  if (isExport(path) && !fromThisSite(request)) {
    return errorResponse(403, "validation_error", "Start the export from Settings.");
  }
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
  if (path[0] === "setup") {
    const token = request.headers.get(SETUP_TOKEN_HEADER);
    if (token !== null) headers.set(SETUP_TOKEN_HEADER, token);
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
  // `no-cache` lets a browser keep the answer on disk; an answer the backend
  // marks `no-store` (the export) keeps that rule.
  const noStore = (upstream.headers.get("cache-control") ?? "")
    .split(",")
    .some((directive) => directive.trim().toLowerCase() === "no-store");
  responseHeaders.set("Cache-Control", noStore ? "no-store" : "no-cache");
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
