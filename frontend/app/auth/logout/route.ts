import * as client from "openid-client";

import { getAuthConfig } from "@/lib/auth-mode";
import { baseUrl, redirectWithCookies } from "@/lib/login";
import { getOidcConfiguration } from "@/lib/oidc";
import { clearSessionCookies, readSession } from "@/lib/session";

// Ends the session, and in oidc mode also the provider's session when the
// provider offers a logout endpoint.
export async function GET(request: Request): Promise<Response> {
  const config = getAuthConfig();
  const base = baseUrl(config, request);
  const cleared = clearSessionCookies(request);
  const home = new URL("/", base);

  if (config.mode !== "oidc") return redirectWithCookies(home, cleared);

  const session = await readSession(request, config.sessionSecret);
  try {
    const oidcConfig = await getOidcConfiguration(config.oidc!);
    if (!oidcConfig.serverMetadata().end_session_endpoint) {
      return redirectWithCookies(home, cleared);
    }
    const parameters: Record<string, string> = {
      post_logout_redirect_uri: home.toString(),
      client_id: config.oidc!.clientId,
    };
    if (session?.idToken) parameters.id_token_hint = session.idToken;
    return redirectWithCookies(client.buildEndSessionUrl(oidcConfig, parameters), cleared);
  } catch (error) {
    console.warn("Logout: could not reach the provider", error instanceof Error ? error.message : error);
    return redirectWithCookies(home, cleared);
  }
}
