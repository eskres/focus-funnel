import * as client from "openid-client";

import { getAuthConfig } from "@/lib/auth-mode";
import {
  LOGIN_COOKIE,
  LOGIN_MAX_AGE_SECONDS,
  baseUrl,
  loginFailedUrl,
  redirectWithCookies,
  safeReturnTo,
  type LoginState,
} from "@/lib/login";
import { getOidcConfiguration } from "@/lib/oidc";
import { seal, serializeCookie } from "@/lib/session";

// Starts a login. In oidc mode this runs the authorization code flow with
// PKCE, state, and nonce; the other modes have their own way in.
export async function GET(request: Request): Promise<Response> {
  const config = getAuthConfig();
  const base = baseUrl(config, request);
  const returnTo = safeReturnTo(new URL(request.url).searchParams.get("returnTo"));

  if (config.mode === "firebase") {
    const login = new URL("/login", base);
    login.searchParams.set("returnTo", returnTo);
    return redirectWithCookies(login);
  }
  if (config.mode === "demo") return redirectWithCookies(new URL(returnTo, base));

  const oidc = config.oidc!;
  let oidcConfig: client.Configuration;
  try {
    oidcConfig = await getOidcConfiguration(oidc);
  } catch (error) {
    console.error("Login: OIDC discovery failed", error instanceof Error ? error.message : error);
    return redirectWithCookies(loginFailedUrl(base));
  }

  const login: LoginState = {
    codeVerifier: client.randomPKCECodeVerifier(),
    state: client.randomState(),
    nonce: client.randomNonce(),
    returnTo,
  };
  const authorizationUrl = client.buildAuthorizationUrl(oidcConfig, {
    redirect_uri: new URL("/auth/callback", base).toString(),
    scope: oidc.scopes,
    code_challenge: await client.calculatePKCECodeChallenge(login.codeVerifier),
    code_challenge_method: "S256",
    state: login.state,
    nonce: login.nonce,
  });
  const sealed = await seal(login, config.sessionSecret, "login", LOGIN_MAX_AGE_SECONDS);
  return redirectWithCookies(authorizationUrl, [
    serializeCookie(LOGIN_COOKIE, sealed, { maxAge: LOGIN_MAX_AGE_SECONDS }),
  ]);
}
