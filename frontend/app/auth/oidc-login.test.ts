// The OIDC login routes against a mocked provider: a local HTTP server that
// serves discovery, keys, and the token endpoint, and signs ID tokens with a
// local key.
import { createHash } from "node:crypto";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { SignJWT, exportJWK, generateKeyPair, type CryptoKey, type JWK } from "jose";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { resetOidcConfiguration } from "@/lib/oidc";
import { LOGIN_COOKIE } from "@/lib/login";
import { SESSION_COOKIE, readSession, sessionCookies } from "@/lib/session";

import { GET as callback } from "./callback/route";
import { GET as login } from "./login/route";
import { GET as logout } from "./logout/route";

const SECRET = "0123456789abcdef0123456789abcdef";
const CLIENT_ID = "focus-funnel";
const CLIENT_SECRET = "client-secret";
const APP = "http://localhost:3000";

interface Grant {
  nonce: string;
  challenge: string;
  claims?: Record<string, unknown>;
}

interface Provider {
  issuer: string;
  internal: string;
  grants: Map<string, Grant>;
  tokenRequests: URLSearchParams[];
  endSession: boolean;
  close: () => Promise<void>;
}

let privateKey: CryptoKey;
let jwk: JWK;

beforeAll(async () => {
  const pair = await generateKeyPair("RS256");
  privateKey = pair.privateKey;
  jwk = { ...(await exportJWK(pair.publicKey)), kid: "key-1", alg: "RS256", use: "sig" };
});

async function idToken(issuer: string, claims: Record<string, unknown>): Promise<string> {
  return new SignJWT({ email: "ana@example.org", email_verified: true, ...claims })
    .setProtectedHeader({ alg: "RS256", kid: "key-1" })
    .setIssuer(issuer)
    // Pocket ID sends the audience as a list.
    .setAudience([CLIENT_ID])
    .setSubject("pocket-user-1")
    .setIssuedAt()
    .setExpirationTime("1h")
    .sign(privateKey);
}

/**
 * A provider reachable only at 127.0.0.1, whose discovery document names its
 * public issuer (unreachable here) on every endpoint, as Pocket ID does.
 */
async function startProvider(options: { publicIssuer?: boolean; endSession?: boolean } = {}) {
  const grants = new Map<string, Grant>();
  const tokenRequests: URLSearchParams[] = [];
  let issuer = "";
  const server: Server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", async () => {
      const url = new URL(req.url ?? "/", "http://provider");
      const send = (status: number, body: unknown) => {
        res.writeHead(status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(body));
      };
      if (url.pathname === "/.well-known/openid-configuration") {
        return send(200, {
          issuer,
          authorization_endpoint: `${issuer}/authorize`,
          token_endpoint: `${issuer}/api/oidc/token`,
          jwks_uri: `${issuer}/.well-known/jwks.json`,
          ...(provider.endSession ? { end_session_endpoint: `${issuer}/api/oidc/end-session` } : {}),
          response_types_supported: ["code"],
          id_token_signing_alg_values_supported: ["RS256"],
          code_challenge_methods_supported: ["S256"],
          token_endpoint_auth_methods_supported: ["client_secret_basic", "client_secret_post"],
          authorization_response_iss_parameter_supported: true,
        });
      }
      if (url.pathname === "/.well-known/jwks.json") return send(200, { keys: [jwk] });
      if (url.pathname === "/api/oidc/token" && req.method === "POST") {
        const form = new URLSearchParams(Buffer.concat(chunks).toString());
        tokenRequests.push(form);
        // RFC 6749 2.3.1: the id and secret are form-encoded inside Basic auth.
        const basic = Buffer.from(
          (req.headers.authorization ?? "").replace(/^Basic /, ""),
          "base64",
        ).toString();
        const [id, secret] = basic.split(":").map(decodeURIComponent);
        if (id !== CLIENT_ID || secret !== CLIENT_SECRET) return send(401, { error: "invalid_client" });
        if (form.get("grant_type") === "refresh_token") {
          if (form.get("refresh_token") !== "refresh-1") return send(400, { error: "invalid_grant" });
          return send(200, {
            access_token: "access-2",
            token_type: "Bearer",
            expires_in: 3600,
            id_token: await idToken(issuer, { nonce: undefined }),
            refresh_token: "refresh-2",
          });
        }
        const grant = grants.get(form.get("code") ?? "");
        const verifier = form.get("code_verifier") ?? "";
        const challenge = createHash("sha256").update(verifier).digest("base64url");
        if (!grant || challenge !== grant.challenge) return send(400, { error: "invalid_grant" });
        return send(200, {
          access_token: "access-1",
          token_type: "Bearer",
          expires_in: 3600,
          id_token: await idToken(issuer, { nonce: grant.nonce, ...grant.claims }),
          refresh_token: "refresh-1",
        });
      }
      send(404, {});
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  const internal = `http://127.0.0.1:${port}`;
  // An address that does not resolve, like http://localhost:1411 seen from a container.
  issuer = options.publicIssuer === false ? internal : `http://pocket-id.invalid:${port}`;
  const provider: Provider = {
    issuer,
    internal,
    grants,
    tokenRequests,
    endSession: options.endSession ?? true,
    close: () => {
      server.closeAllConnections();
      return new Promise((resolve) => server.close(() => resolve()));
    },
  };
  return provider;
}

let provider: Provider;

function useOidc(extra: Record<string, string> = {}) {
  const env = {
    AUTH_MODE: "oidc",
    SESSION_SECRET: SECRET,
    APP_BASE_URL: APP,
    OIDC_ISSUER: provider.issuer,
    OIDC_CLIENT_ID: CLIENT_ID,
    OIDC_CLIENT_SECRET: CLIENT_SECRET,
    OIDC_INTERNAL_URL: provider.issuer === provider.internal ? "" : provider.internal,
    ...extra,
  };
  for (const [name, value] of Object.entries(env)) vi.stubEnv(name, value);
}

const cookiePairs = (response: Response) =>
  response.headers
    .getSetCookie()
    .map((header) => header.split(";")[0])
    .filter((pair) => !pair.endsWith("="))
    .join("; ");

/** Starts a login and plays the provider's part: returns the callback request. */
async function loginAndAuthorize(returnTo = "/app/abc", claims?: Record<string, unknown>) {
  const started = await login(new Request(`${APP}/auth/login?returnTo=${encodeURIComponent(returnTo)}`));
  expect(started.status).toBe(303);
  const authorize = new URL(started.headers.get("location")!);
  const code = `code-${provider.grants.size + 1}`;
  provider.grants.set(code, {
    nonce: authorize.searchParams.get("nonce")!,
    challenge: authorize.searchParams.get("code_challenge")!,
    claims,
  });
  const params = new URLSearchParams({
    code,
    state: authorize.searchParams.get("state")!,
    iss: provider.issuer,
  });
  return {
    authorize,
    cookie: cookiePairs(started),
    callbackUrl: `${APP}/auth/callback?${params}`,
  };
}

const withCookie = (url: string, cookie: string) => new Request(url, { headers: { cookie } });

beforeEach(async () => {
  resetOidcConfiguration();
  provider = await startProvider();
  useOidc();
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(async () => {
  await provider.close();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("/auth/login", () => {
  it("sends the browser to the provider's public authorization endpoint with PKCE, state, and nonce", async () => {
    const { authorize, cookie } = await loginAndAuthorize();

    expect(authorize.origin).toBe(new URL(provider.issuer).origin);
    expect(authorize.pathname).toBe("/authorize");
    expect(authorize.searchParams.get("client_id")).toBe(CLIENT_ID);
    expect(authorize.searchParams.get("redirect_uri")).toBe(`${APP}/auth/callback`);
    expect(authorize.searchParams.get("scope")).toBe("openid email profile offline_access");
    expect(authorize.searchParams.get("code_challenge_method")).toBe("S256");
    expect(authorize.searchParams.get("state")).toBeTruthy();
    expect(authorize.searchParams.get("nonce")).toBeTruthy();
    expect(cookie).toContain(`${LOGIN_COOKIE}=`);
  });

  it("keeps the login state in an HttpOnly cookie", async () => {
    const started = await login(new Request(`${APP}/auth/login`));
    const [header] = started.headers.getSetCookie();
    expect(header).toMatch(new RegExp(`^${LOGIN_COOKIE}=.*HttpOnly; Secure; SameSite=Lax`));
  });
});

describe("/auth/callback", () => {
  it("starts a session and returns to returnTo", async () => {
    const { cookie, callbackUrl } = await loginAndAuthorize("/app/abc?x=1");

    const response = await callback(withCookie(callbackUrl, cookie));

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(`${APP}/app/abc?x=1`);
    const setCookies = response.headers.getSetCookie();
    expect(setCookies.some((c) => c.startsWith(`${LOGIN_COOKIE}=;`) && c.includes("Max-Age=0"))).toBe(true);
    const session = await readSession(withCookie(APP, cookiePairs(response)), SECRET);
    expect(session).toMatchObject({ mode: "oidc", refreshToken: "refresh-1" });
    expect(session?.idToken.split(".")).toHaveLength(3);
    // The tokens are not readable in any cookie.
    expect(setCookies.join()).not.toContain(session!.idToken);
    expect(setCookies.join()).not.toContain("refresh-1");
  });

  it("calls the token endpoint through OIDC_INTERNAL_URL", async () => {
    const { cookie, callbackUrl } = await loginAndAuthorize();
    const response = await callback(withCookie(callbackUrl, cookie));
    expect(response.headers.get("location")).toBe(`${APP}/app/abc`);
    expect(provider.tokenRequests).toHaveLength(1);
  });

  it("works without OIDC_INTERNAL_URL when the issuer is reachable", async () => {
    await provider.close();
    resetOidcConfiguration();
    provider = await startProvider({ publicIssuer: false });
    useOidc();
    const { cookie, callbackUrl } = await loginAndAuthorize();
    const response = await callback(withCookie(callbackUrl, cookie));
    expect(response.headers.get("location")).toBe(`${APP}/app/abc`);
  });

  it("shows the login-failed page for a wrong state", async () => {
    const { cookie, callbackUrl } = await loginAndAuthorize();
    const url = new URL(callbackUrl);
    url.searchParams.set("state", "forged-state");

    const response = await callback(withCookie(url.toString(), cookie));

    expect(response.headers.get("location")).toBe(`${APP}/auth/error`);
    expect(response.headers.getSetCookie().join()).not.toContain(`${SESSION_COOKIE}=e`);
  });

  it("shows the login-failed page for a wrong nonce", async () => {
    const { cookie, callbackUrl } = await loginAndAuthorize();
    const code = new URL(callbackUrl).searchParams.get("code")!;
    provider.grants.get(code)!.nonce = "another-nonce";

    const response = await callback(withCookie(callbackUrl, cookie));

    expect(response.headers.get("location")).toBe(`${APP}/auth/error`);
    expect(response.headers.getSetCookie().some((c) => c.startsWith(`${SESSION_COOKIE}=`))).toBe(false);
  });

  it("shows the login-failed page when the provider returns an error", async () => {
    const { cookie } = await loginAndAuthorize();

    const response = await callback(
      withCookie(`${APP}/auth/callback?error=access_denied&state=x&iss=${provider.issuer}`, cookie),
    );

    expect(response.headers.get("location")).toBe(`${APP}/auth/error`);
    expect(provider.tokenRequests).toHaveLength(0);
  });

  it("shows the login-failed page without the login cookie", async () => {
    const { callbackUrl } = await loginAndAuthorize();
    const response = await callback(new Request(callbackUrl));
    expect(response.headers.get("location")).toBe(`${APP}/auth/error`);
  });

  it("does not return to another site", async () => {
    const { cookie, callbackUrl } = await loginAndAuthorize("//evil.example/steal");
    const response = await callback(withCookie(callbackUrl, cookie));
    expect(response.headers.get("location")).toBe(`${APP}/app`);
  });
});

describe("allow-list in the callback", () => {
  it("shows the not-allowed page to an unlisted address and starts no session", async () => {
    useOidc({ AUTH_ALLOWED_EMAILS: "bo@example.org" });
    const { cookie, callbackUrl } = await loginAndAuthorize();

    const response = await callback(withCookie(callbackUrl, cookie));

    expect(response.headers.get("location")).toBe(`${APP}/auth/not-allowed`);
    expect(response.headers.getSetCookie().some((c) => c.startsWith(`${SESSION_COOKIE}`))).toBe(false);
  });

  it("refuses an address the provider has not verified", async () => {
    useOidc({ AUTH_ALLOWED_EMAILS: "ana@example.org" });
    const { cookie, callbackUrl } = await loginAndAuthorize("/app", { email_verified: false });
    const response = await callback(withCookie(callbackUrl, cookie));
    expect(response.headers.get("location")).toBe(`${APP}/auth/not-allowed`);
  });

  it("lets a listed domain in", async () => {
    useOidc({ AUTH_ALLOWED_EMAILS: "@example.org" });
    const { cookie, callbackUrl } = await loginAndAuthorize();
    const response = await callback(withCookie(callbackUrl, cookie));
    expect(response.headers.get("location")).toBe(`${APP}/app/abc`);
  });
});

describe("/auth/logout", () => {
  async function loggedIn(): Promise<string> {
    const headers = await sessionCookies(
      new Request(APP),
      { mode: "oidc", idToken: "the-id-token", refreshToken: "r", expiresAt: 9999999999 },
      SECRET,
    );
    return headers.map((h) => h.split(";")[0]).join("; ");
  }

  it("clears the cookie and redirects to the provider's end_session_endpoint", async () => {
    const response = await logout(withCookie(`${APP}/auth/logout`, await loggedIn()));

    const location = new URL(response.headers.get("location")!);
    expect(location.origin).toBe(new URL(provider.issuer).origin);
    expect(location.pathname).toBe("/api/oidc/end-session");
    expect(location.searchParams.get("post_logout_redirect_uri")).toBe(`${APP}/`);
    expect(location.searchParams.get("id_token_hint")).toBe("the-id-token");
    expect(response.headers.getSetCookie()).toEqual([
      expect.stringMatching(new RegExp(`^${SESSION_COOKIE}=;.*Max-Age=0`)),
    ]);
  });

  it("redirects home when the provider has no logout endpoint", async () => {
    await provider.close();
    resetOidcConfiguration();
    provider = await startProvider({ endSession: false });
    useOidc();

    const response = await logout(withCookie(`${APP}/auth/logout`, await loggedIn()));

    expect(response.headers.get("location")).toBe(`${APP}/`);
    expect(response.headers.getSetCookie()[0]).toContain("Max-Age=0");
  });
});

describe("renewal through the refresh grant", () => {
  it("renews the ID token and rotates the refresh token", async () => {
    const { refreshOidcSession } = await import("@/lib/oidc");
    const { readAuthConfig } = await import("@/lib/auth-mode");
    const session = await refreshOidcSession(readAuthConfig().oidc!, "refresh-1");
    expect(session.refreshToken).toBe("refresh-2");
    expect(session.expiresAt).toBeGreaterThan(Date.now() / 1000);
    await expect(refreshOidcSession(readAuthConfig().oidc!, "revoked")).rejects.toThrow();
  });
});
