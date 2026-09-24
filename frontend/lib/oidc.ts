// The OpenID Connect client for oidc mode, run on the Next.js server with
// openid-client. Works with any provider that publishes a discovery document.

import * as client from "openid-client";

import type { OidcConfig } from "@/lib/auth-mode";
import type { Session } from "@/lib/session";

// Endpoints the browser is sent to keep the public origin. Every other
// endpoint is called by this server, so OIDC_INTERNAL_URL replaces its origin.
const BROWSER_ENDPOINTS = new Set(["authorization_endpoint", "end_session_endpoint"]);

/** Points a URL on the issuer's public origin at the internal address instead. */
export function replaceOrigin(url: string, issuer: string, internalUrl: string | null): string {
  if (!internalUrl) return url;
  const target = new URL(url);
  if (target.origin !== new URL(issuer).origin) return url;
  const internal = new URL(internalUrl);
  target.protocol = internal.protocol;
  target.host = internal.host;
  return target.toString();
}

/**
 * The discovery document with every server-to-server endpoint moved to the
 * internal address. The discovery document names the public origin on every
 * endpoint, which the container may not reach.
 */
export function internalMetadata(
  metadata: client.ServerMetadata,
  oidc: Pick<OidcConfig, "issuer" | "internalUrl">,
): client.ServerMetadata {
  const rewritten: Record<string, unknown> = { ...metadata };
  for (const [name, value] of Object.entries(metadata)) {
    if (BROWSER_ENDPOINTS.has(name) || typeof value !== "string") continue;
    if (name.endsWith("_endpoint") || name === "jwks_uri") {
      rewritten[name] = replaceOrigin(value, oidc.issuer, oidc.internalUrl);
    }
  }
  const aliases = metadata.mtls_endpoint_aliases;
  if (aliases) {
    rewritten.mtls_endpoint_aliases = Object.fromEntries(
      Object.entries(aliases).map(([name, value]) => [
        name,
        typeof value === "string" ? replaceOrigin(value, oidc.issuer, oidc.internalUrl) : value,
      ]),
    );
  }
  return rewritten as client.ServerMetadata;
}

function clientAuthentication(metadata: client.ServerMetadata, secret: string): client.ClientAuth {
  const methods = metadata.token_endpoint_auth_methods_supported;
  // RFC 8414: client_secret_basic is the default when the list is absent.
  if (!methods || methods.includes("client_secret_basic")) return client.ClientSecretBasic(secret);
  return client.ClientSecretPost(secret);
}

let cached: { key: string; config: Promise<client.Configuration> } | null = null;

/** Reads the provider's discovery document once per process. */
export function getOidcConfiguration(oidc: OidcConfig): Promise<client.Configuration> {
  const key = JSON.stringify([oidc.issuer, oidc.clientId, oidc.internalUrl]);
  if (cached?.key === key) return cached.config;
  const config = discover(oidc);
  cached = { key, config };
  // A failed discovery is tried again on the next request.
  config.catch(() => {
    if (cached?.config === config) cached = null;
  });
  return config;
}

/** Forgets the discovered configuration (tests start each case fresh). */
export function resetOidcConfiguration() {
  cached = null;
}

async function discover(oidc: OidcConfig): Promise<client.Configuration> {
  const issuer = oidc.issuer.replace(/\/$/, "");
  const discoveryUrl = replaceOrigin(
    `${issuer}/.well-known/openid-configuration`,
    oidc.issuer,
    oidc.internalUrl,
  );
  const response = await fetch(discoveryUrl, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`OIDC discovery failed with status ${response.status}`);
  }
  const metadata = (await response.json()) as client.ServerMetadata;
  // The document must name the configured issuer; "iss" in tokens is checked against it.
  if (metadata.issuer.replace(/\/$/, "") !== issuer) {
    throw new Error(`OIDC discovery names issuer ${metadata.issuer}, not OIDC_ISSUER ${oidc.issuer}`);
  }
  const config = new client.Configuration(
    internalMetadata(metadata, oidc),
    oidc.clientId,
    undefined,
    clientAuthentication(metadata, oidc.clientSecret),
  );
  const addresses = [oidc.issuer, oidc.internalUrl].filter(Boolean) as string[];
  if (addresses.some((address) => new URL(address).protocol === "http:")) {
    // A local provider such as Pocket ID on http://localhost:1411.
    client.allowInsecureRequests(config);
  }
  // Also check the ID token's signature against the provider's keys.
  client.enableNonRepudiationChecks(config);
  return config;
}

/** The session for a token response that holds an ID token. */
export function sessionFromTokens(
  tokens: client.TokenEndpointResponse & client.TokenEndpointResponseHelpers,
  previousRefreshToken: string | null,
): Session {
  const claims = tokens.claims();
  if (!tokens.id_token || !claims) throw new Error("The provider returned no ID token.");
  return {
    mode: "oidc",
    idToken: tokens.id_token,
    // A provider may keep the same refresh token and not send it again.
    refreshToken: tokens.refresh_token ?? previousRefreshToken,
    expiresAt: claims.exp,
  };
}

/** Renews the ID token with the refresh grant. */
export async function refreshOidcSession(oidc: OidcConfig, refreshToken: string): Promise<Session> {
  const config = await getOidcConfiguration(oidc);
  const tokens = await client.refreshTokenGrant(config, refreshToken);
  return sessionFromTokens(tokens, refreshToken);
}
