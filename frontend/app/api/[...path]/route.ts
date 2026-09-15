import { auth0 } from "@/lib/auth0";

// Forwards every /api/... call to the private FastAPI backend with the user's
// Auth0 access token. The token is read on the server and never sent to the
// browser. Response bodies are streamed through without buffering.

// Request headers passed on to the backend. Cookies (the Auth0 session) and
// any client-sent Authorization header are deliberately not forwarded.
const FORWARDED_REQUEST_HEADERS = ["accept", "accept-language", "content-type"];

// Response headers that describe the upstream connection or encoding rather
// than the body we stream on.
const DROPPED_RESPONSE_HEADERS = [
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "transfer-encoding",
];

function unauthenticated() {
  return Response.json(
    { error: { code: "unauthenticated", message: "Log in to continue." } },
    { status: 401 },
  );
}

async function getAccessToken(): Promise<string | null> {
  try {
    const session = await auth0.getSession();
    if (!session) return null;
    const { token } = await auth0.getAccessToken();
    return token;
  } catch {
    // No session, an expired session, or a failed token refresh.
    return null;
  }
}

async function forward(request: Request): Promise<Response> {
  const token = await getAccessToken();
  if (!token) return unauthenticated();

  const backendUrl = process.env.BACKEND_URL;
  if (!backendUrl) {
    return Response.json(
      { error: { code: "internal_error", message: "BACKEND_URL is not set." } },
      { status: 500 },
    );
  }

  const incoming = new URL(request.url);
  const target = new URL(
    incoming.pathname + incoming.search,
    backendUrl.endsWith("/") ? backendUrl : `${backendUrl}/`,
  );

  const headers = new Headers({ Authorization: `Bearer ${token}` });
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      // Required by Node's fetch to send a streamed request body.
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual",
      cache: "no-store",
      signal: request.signal,
    } as RequestInit);
  } catch {
    return Response.json(
      {
        error: {
          code: "backend_unreachable",
          message: "The server could not be reached. Try again.",
        },
      },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers(upstream.headers);
  for (const name of DROPPED_RESPONSE_HEADERS) responseHeaders.delete(name);
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
