// Firebase ID tokens on the Next.js server: checked against Google's published
// keys, and renewed through the securetoken endpoint with the public web API
// key. No Firebase Admin SDK and no service account.

import { createRemoteJWKSet, jwtVerify, type JWTPayload, type JWTVerifyGetKey } from "jose";

import type { FirebaseConfig } from "@/lib/auth-mode";
import type { Session } from "@/lib/session";

export const FIREBASE_JWKS_URL =
  "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com";
export const SECURETOKEN_URL = "https://securetoken.googleapis.com/v1/token";

let keySet: JWTVerifyGetKey = createRemoteJWKSet(new URL(FIREBASE_JWKS_URL));

/** Tests replace Google's key set with a local one. */
export function setFirebaseKeySet(keys: JWTVerifyGetKey | null) {
  keySet = keys ?? createRemoteJWKSet(new URL(FIREBASE_JWKS_URL));
}

export interface FirebaseClaims extends JWTPayload {
  sub: string;
  exp: number;
  email?: string;
  email_verified?: boolean;
}

export class FirebaseTokenError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FirebaseTokenError";
  }
}

/** Checks a Firebase ID token for this project; throws FirebaseTokenError when it is not valid. */
export async function verifyFirebaseIdToken(
  idToken: string,
  firebase: Pick<FirebaseConfig, "projectId">,
): Promise<FirebaseClaims> {
  try {
    const { payload } = await jwtVerify(idToken, keySet, {
      issuer: `https://securetoken.google.com/${firebase.projectId}`,
      audience: firebase.projectId,
      algorithms: ["RS256"],
      requiredClaims: ["sub", "exp", "iat"],
    });
    if (typeof payload.sub !== "string" || payload.sub === "") {
      throw new FirebaseTokenError("The token has no subject.");
    }
    return payload as FirebaseClaims;
  } catch (error) {
    if (error instanceof FirebaseTokenError) throw error;
    throw new FirebaseTokenError(error instanceof Error ? error.message : String(error));
  }
}

/** Renews the ID token with the refresh token and the project's web API key. */
export async function refreshFirebaseSession(
  firebase: FirebaseConfig,
  refreshToken: string,
): Promise<Session> {
  const url = new URL(SECURETOKEN_URL);
  url.searchParams.set("key", firebase.apiKey);
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: refreshToken }),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new FirebaseTokenError(`Firebase refused to renew the token (status ${response.status}).`);
  }
  const body = (await response.json()) as { id_token?: string; refresh_token?: string };
  if (!body.id_token) throw new FirebaseTokenError("Firebase returned no ID token.");
  const claims = await verifyFirebaseIdToken(body.id_token, firebase);
  return {
    mode: "firebase",
    idToken: body.id_token,
    refreshToken: body.refresh_token ?? refreshToken,
    expiresAt: claims.exp,
  };
}
