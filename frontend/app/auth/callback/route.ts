import * as client from "openid-client";

import { isAllowed } from "@/lib/allow-list";
import { getAuthConfig } from "@/lib/auth-mode";
import {
  LOGIN_COOKIE,
  baseUrl,
  loginFailedUrl,
  notAllowedUrl,
  redirectWithCookies,
  type LoginState,
} from "@/lib/login";
import { getOidcConfiguration, sessionFromTokens } from "@/lib/oidc";
import { clearCookie, readCookies, sessionCookies, unseal } from "@/lib/session";

// Finishes an oidc login: checks state, PKCE, and nonce, exchanges the code,
// verifies the ID token, applies the allow-list, and starts the session.
export async function GET(request: Request): Promise<Response> {
  const config = getAuthConfig();
  const base = baseUrl(config, request);
  const clearLogin = clearCookie(LOGIN_COOKIE);
  const failed = () => redirectWithCookies(loginFailedUrl(base), [clearLogin]);

  if (config.mode !== "oidc") return redirectWithCookies(new URL("/", base));

  const login = await unseal<LoginState>(
    readCookies(request).get(LOGIN_COOKIE),
    config.sessionSecret,
    "login",
  );
  const params = new URL(request.url).searchParams;
  if (!login || params.has("error")) {
    if (params.has("error")) {
      console.warn("Login: the provider returned an error", { error: params.get("error") });
    }
    return failed();
  }

  let tokens: Awaited<ReturnType<typeof client.authorizationCodeGrant>>;
  try {
    const oidcConfig = await getOidcConfiguration(config.oidc!);
    // The URL the provider sent the browser to, on the public base URL, so it
    // matches the redirect_uri of the login.
    const currentUrl = new URL(`/auth/callback${new URL(request.url).search}`, base);
    tokens = await client.authorizationCodeGrant(oidcConfig, currentUrl, {
      pkceCodeVerifier: login.codeVerifier,
      expectedState: login.state,
      expectedNonce: login.nonce,
      idTokenExpected: true,
    });
  } catch (error) {
    console.warn("Login: the callback was refused", {
      reason: error instanceof Error ? `${error.name}: ${error.message}` : "unknown",
    });
    return failed();
  }

  const claims = tokens.claims();
  if (!isAllowed(claims?.email, claims?.email_verified, config.allowedEmails)) {
    return redirectWithCookies(notAllowedUrl(base), [clearLogin]);
  }

  const session = sessionFromTokens(tokens, null);
  return redirectWithCookies(new URL(login.returnTo, base), [
    clearLogin,
    ...(await sessionCookies(request, session, config.sessionSecret)),
  ]);
}
