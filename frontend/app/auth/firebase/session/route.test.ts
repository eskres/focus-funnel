import { SignJWT, createLocalJWKSet, exportJWK, generateKeyPair, type CryptoKey } from "jose";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { getBackendCredential, resetRenewals } from "@/lib/auth-mode";
import {
  SECURETOKEN_URL,
  refreshFirebaseSession,
  setFirebaseKeySet,
} from "@/lib/firebase-server";
import { SESSION_COOKIE, readSession, sessionCookies } from "@/lib/session";

import { POST } from "./route";

const SECRET = "0123456789abcdef0123456789abcdef";
const PROJECT = "focus-funnel";
const APP = "http://localhost:3000";
const FIREBASE = {
  projectId: PROJECT,
  apiKey: "public-web-api-key",
  authDomain: "focus-funnel.firebaseapp.com",
};

let privateKey: CryptoKey;

beforeAll(async () => {
  const pair = await generateKeyPair("RS256");
  privateKey = pair.privateKey;
  const jwk = { ...(await exportJWK(pair.publicKey)), kid: "google-key", alg: "RS256" };
  setFirebaseKeySet(createLocalJWKSet({ keys: [jwk] }));
});

function firebaseToken(options: { project?: string; expiresIn?: string; sub?: string } = {}) {
  const project = options.project ?? PROJECT;
  return new SignJWT({ email: "ana@example.org", email_verified: true })
    .setProtectedHeader({ alg: "RS256", kid: "google-key" })
    .setIssuer(`https://securetoken.google.com/${project}`)
    .setAudience(project)
    .setSubject(options.sub ?? "firebase-uid")
    .setIssuedAt()
    .setExpirationTime(options.expiresIn ?? "1h")
    .sign(privateKey);
}

beforeEach(() => {
  for (const [name, value] of Object.entries({
    AUTH_MODE: "firebase",
    SESSION_SECRET: SECRET,
    APP_BASE_URL: APP,
    FIREBASE_PROJECT_ID: FIREBASE.projectId,
    FIREBASE_API_KEY: FIREBASE.apiKey,
    FIREBASE_AUTH_DOMAIN: FIREBASE.authDomain,
  })) {
    vi.stubEnv(name, value);
  }
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  resetRenewals();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const post = (body: unknown, origin = APP) =>
  POST(
    new Request(`${APP}/auth/firebase/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Origin: origin },
      body: JSON.stringify(body),
    }),
  );

const cookiePairs = (response: Response) =>
  response.headers.getSetCookie().map((h) => h.split(";")[0]).join("; ");

describe("/auth/firebase/session", () => {
  it("starts a session for a valid token", async () => {
    const idToken = await firebaseToken();

    const response = await post({ idToken, refreshToken: "refresh-1", returnTo: "/app/abc" });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ redirect: "/app/abc" });
    const [cookie] = response.headers.getSetCookie();
    expect(cookie).toMatch(new RegExp(`^${SESSION_COOKIE}=.*HttpOnly; Secure; SameSite=Lax`));
    expect(cookie).not.toContain(idToken);
    const session = await readSession(
      new Request(APP, { headers: { cookie: cookiePairs(response) } }),
      SECRET,
    );
    expect(session).toMatchObject({ mode: "firebase", idToken, refreshToken: "refresh-1" });
  });

  it("refuses a token from another project", async () => {
    const response = await post({
      idToken: await firebaseToken({ project: "someone-elses-project" }),
      refreshToken: "refresh-1",
    });
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ error: { code: "unauthenticated" } });
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("refuses an expired or forged token", async () => {
    const expired = await post({ idToken: await firebaseToken({ expiresIn: "-1m" }), refreshToken: "r" });
    expect(expired.status).toBe(401);
    const forged = await post({ idToken: "a.b.c", refreshToken: "r" });
    expect(forged.status).toBe(401);
  });

  it("refuses a request from another site", async () => {
    const response = await post(
      { idToken: await firebaseToken(), refreshToken: "r" },
      "https://evil.example",
    );
    expect(response.status).toBe(403);
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("refuses an address off the allow-list with not_allowed", async () => {
    vi.stubEnv("AUTH_ALLOWED_EMAILS", "bo@example.org");
    const response = await post({ idToken: await firebaseToken(), refreshToken: "r" });
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ error: { code: "not_allowed" } });
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("is not found in other modes", async () => {
    vi.stubEnv("AUTH_MODE", "demo");
    for (const name of ["FIREBASE_PROJECT_ID", "FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN"]) {
      vi.stubEnv(name, "");
    }
    const response = await post({ idToken: "x", refreshToken: "y" });
    expect(response.status).toBe(404);
  });
});

describe("renewal through the securetoken endpoint", () => {
  it("replaces the token using only the web API key", async () => {
    const renewed = await firebaseToken();
    const fetchMock = vi.fn(async () =>
      Response.json({ id_token: renewed, refresh_token: "refresh-2", expires_in: "3600" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const session = await refreshFirebaseSession(FIREBASE, "refresh-1");

    expect(session).toMatchObject({ mode: "firebase", idToken: renewed, refreshToken: "refresh-2" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(`${url.origin}${url.pathname}`).toBe(SECURETOKEN_URL);
    expect(url.searchParams.get("key")).toBe(FIREBASE.apiKey);
    expect(String(init.body)).toBe("grant_type=refresh_token&refresh_token=refresh-1");
  });

  it("renews an expiring session before the API call", async () => {
    const renewed = await firebaseToken();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ id_token: renewed, refresh_token: "refresh-2" })),
    );
    const old = await sessionCookies(
      new Request(APP),
      {
        mode: "firebase",
        idToken: "old-token",
        refreshToken: "refresh-1",
        expiresAt: Math.floor(Date.now() / 1000) + 20,
      },
      SECRET,
    );
    const request = new Request(`${APP}/api/me`, {
      headers: { cookie: old.map((h) => h.split(";")[0]).join("; ") },
    });

    const result = await getBackendCredential(request);

    expect(result).toMatchObject({ credential: renewed });
  });

  it("fails when Google refuses the refresh token", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ error: {} }, { status: 400 })));
    await expect(refreshFirebaseSession(FIREBASE, "revoked")).rejects.toThrow();
  });

  it("refuses a renewed token for another project", async () => {
    const other = await firebaseToken({ project: "other" });
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ id_token: other })));
    await expect(refreshFirebaseSession(FIREBASE, "refresh-1")).rejects.toThrow();
  });
});
