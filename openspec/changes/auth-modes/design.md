## Context

`platform-foundation` wires login to Auth0 on both sides:

- **Frontend:** `@auth0/nextjs-auth0` in `lib/auth0.ts` mounts `/auth/login`, `/auth/callback`, and `/auth/logout` through `proxy.ts`, keeps the session in an encrypted cookie, and the API proxy (`app/api/[...path]/route.ts`) reads the access token on the server and forwards it as a bearer token.
- **Backend:** `app/auth.py` verifies an RS256 access token against the tenant's JWKS (`JwksCache`), with `AUTH0_DOMAIN` and `AUTH0_AUDIENCE`, and `get_or_create_user()` inserts one `users` row per `auth0_sub` with `ON CONFLICT DO NOTHING`.
- **Settings:** `Settings` requires `auth0_domain` and `auth0_audience`, so the backend cannot start without Auth0.

`model-providers` and `conversation-agent` have landed, so provider keys live in `provider_keys`, the key lookup goes through `client_for()`, and conversations, messages, usage, loadout, and settings all cascade from `users`. See `proposal.md` for why.

## Goals / Non-Goals

**Goals:**

- One place in the backend, and one in the frontend server, that knows the auth mode. Everything after "who is this user" is unchanged.
- The same container images serve all three modes. The mode is read at run time, not baked into the frontend build.
- No secret beyond the provider's own client settings. Firebase works without a service account.

**Non-Goals:**

- Built-in username and password accounts.
- Several login providers at once, or linking one user across providers.
- Roles or an admin user. The allow-list is the only access control.
- Scaling demo mode past one instance.

## Decisions

### 1. The backend verifies an ID token, in every real mode

In `oidc` mode the backend verifies the OIDC **ID token**, not the access token. The OIDC standard guarantees that an ID token is a signed JWT with `iss`, `aud` (the client id), `sub`, and `exp`. Access tokens may be opaque, and their audience differs by provider (Auth0 needs an API audience, Pocket ID has none). The backend reads `jwks_uri` from the issuer's discovery document and reuses `JwksCache`.

In `firebase` mode the backend verifies the Firebase ID token against Google's public keys (`https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com`), with issuer `https://securetoken.google.com/<project>` and audience `<project>`. No Firebase Admin SDK and no service account.

Accepted algorithms are the asymmetric ones (`RS256`, `ES256`, `EdDSA`) intersected with what the discovery document lists. `HS*` and `none` are always refused.

**Alternatives:** verify the access token (rejected: may be opaque, and needs a provider-specific audience); the frontend server verifies login and signs its own internal token for the backend (rejected: adds a shared secret between the two, and a leaked secret lets anyone mint any user); Firebase session cookies (rejected: need a service account for `createSessionCookie`).

### 2. One `authenticate` step with three implementations

`get_current_user` depends on `authenticate(request) -> Identity(issuer, subject, email, email_verified)`, picked once from `AUTH_MODE` at startup: `OidcAuthenticator`, `FirebaseAuthenticator`, `DemoAuthenticator`. After it, `get_or_create_user(session, identity)` runs the allow-list check (decision 10) and the existing insert. Routers and ownership checks do not change.

A missing signing key when JWKS cannot be fetched stays a `503 service_unavailable`, as today.

### 3. Users are keyed by issuer and subject

The migration renames `users.auth0_sub` to `subject`, adds `issuer TEXT NOT NULL`, and replaces the unique index with `UNIQUE (issuer, subject)`. It also adds `expires_at TIMESTAMPTZ NULL` (demo users only) and `demo_notice_accepted_at TIMESTAMPTZ NULL`.

Existing rows get `issuer = 'auth0-legacy'`. No login ever produces that issuer, so those rows are never matched again. There are no users besides the developer, so no relinking tool is built. The developer re-enters their provider key after the switch, or resets the local database.

For a demo user, `issuer = 'demo'` and `subject` is the SHA-256 hex of the session value, so the same unique index finds them and the database never holds a usable session value.

### 4. The frontend server owns the session

`@auth0/nextjs-auth0` is removed. `lib/session.ts` keeps one encrypted, HttpOnly, Secure, SameSite=Lax cookie (`ff_session`), sealed with `jose` (`dir` + `A256GCM`) under `SESSION_SECRET` (renamed from `AUTH0_SECRET`). It holds the ID token, the refresh token, the expiry, and the path to return to. Nothing is stored on the server, so the frontend stays stateless.

`lib/auth-mode.ts` reads `AUTH_MODE` on the server and exposes `getBackendCredential(request)`, which the API proxy calls instead of `auth0.getAccessToken()`:

- `oidc` and `firebase`: return the ID token, renewing it first if it expires within 60 seconds (decision 5). A renewal failure clears the cookie and returns 401 `unauthenticated`.
- `demo`: return the demo session value from its cookie (decision 7).

Pages learn the mode from a server component, never from a `NEXT_PUBLIC_*` variable, so one image serves every mode.

If the sealed cookie would pass 3,800 bytes, it is split into numbered chunks, as the Auth0 SDK does. Most providers' tokens fit in one.

### 5. OIDC flow and renewal

`openid-client` (v6) runs the authorization code flow with PKCE, `state`, and `nonce` on the Next.js server. `/auth/login` stores the PKCE verifier, state, nonce, and return path in a short-lived sealed cookie and redirects. `/auth/callback` checks them, exchanges the code, verifies the ID token and nonce, and starts the session. `/auth/logout` clears the cookie and redirects to the provider's `end_session_endpoint` when there is one. The paths stay the same as today, so the landing page link and `proxy.ts` redirects do not change.

Scopes default to `openid email profile offline_access`. With a refresh token, renewal uses the refresh grant. Without one (a provider that refuses `offline_access`), the session ends when the ID token expires and the user logs in again.

**Discovery from inside compose.** The issuer is a public URL such as `http://localhost:1411`, which the containers cannot reach. `OIDC_INTERNAL_URL` (optional) replaces the issuer's origin for server-to-server calls (discovery, JWKS, token) while `iss` is still checked against `OIDC_ISSUER`. Both the backend and the frontend server use it.

### 6. Firebase flow and renewal

The login page loads the Firebase web SDK with the project's public config (`FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_PROJECT_ID`, served by a server component). It uses `inMemoryPersistence`, offers Google and email-and-password sign-in, then posts the ID token and refresh token to `/auth/firebase/session` and calls `signOut()`. The server verifies the ID token as the backend does, then starts the session. Renewal calls `https://securetoken.googleapis.com/v1/token?key=<API_KEY>` with the refresh token.

The Firebase web API key is public by design and identifies the project. It is not a secret.

### 7. Demo sessions

- **Start:** when a page request has no `ff_demo` cookie, `proxy.ts` calls `POST /api/demo/sessions` on the backend. The backend makes 32 random bytes (base64url), stores a user with `issuer = 'demo'`, `subject = sha256(value)`, and `expires_at = now + DEMO_SESSION_TTL_HOURS`, and returns the value and the expiry. `proxy.ts` sets it as an HttpOnly, Secure, SameSite=Lax cookie with a matching `Max-Age`. The endpoint exists only in demo mode and refuses with `503 demo_full` when `DEMO_MAX_SESSIONS` live users exist.
- **Use:** the API proxy sends the value as the bearer credential. `DemoAuthenticator` hashes it and looks up the user, refusing an expired one with `401 demo_session_expired`. The proxy then clears the cookie, and the page offers a new session.
- **End:** `DELETE /api/demo/session` deletes the user now.
- **Cleanup:** a lifespan task runs every 5 minutes and deletes users with `expires_at < now()`. Every user-owned table cascades from `users`. The deletion goes through one `delete_user_data(user)` function, which `thought-storage` extends to drop Chroma collections.
- **Notice:** `POST /api/demo/notice` sets `demo_notice_accepted_at`, and `GET /api/me` returns the mode, the expiry, and whether the notice is accepted. The composer is blocked until it is. The backend does not enforce it: skipping it through the API harms only the person who skips it.

**Alternative:** a separate `demo_sessions` table (rejected: the user row already has everything, and one unique index serves every mode).

### 8. Demo keys in an encrypted cookie

The proposal asks for keys held by the browser, not the server. They are held in an HttpOnly cookie (`ff_demo_keys`) sealed under `SESSION_SECRET`, not in `sessionStorage`, so a script injected into the page cannot read them. The cookie holds `{ provider_id: { key, set_at } , last_used_at }`.

- **Save:** `PUT /api/providers/{id}/key` passes through the proxy to the backend, which in demo mode checks the key with the provider and answers `{ held: true, key_last4 }` without writing a row. The proxy sees a 200 on that route in demo mode and adds the key to the cookie. The key is in the request body once and in the cookie afterwards.
- **Use:** on every API call the proxy drops keys past `DEMO_KEY_TTL_MINUTES` idle or `DEMO_KEY_MAX_HOURS` old, sends the rest in `X-Provider-Keys` (base64url JSON of `{ provider_id: { key, expires_at } }`), and re-seals the cookie with a fresh `last_used_at`.
- **Backend:** in demo mode the key lookup behind `client_for()` reads the request's keys instead of `provider_keys`, and `GET /api/providers` reports key status from them. Outside demo mode the header is ignored. The header name is added to the log masking list.
- **Forget:** `DELETE /api/providers/{id}/key` is answered by the proxy in demo mode by removing that key from the cookie. The backend is not called.

### 9. Demo guards

- `Settings` refuses to start in demo mode when any `OIDC_*` or `FIREBASE_*` value is set, or when `ALLOW_CUSTOM_PROVIDER=true` is set explicitly. Otherwise it forces the custom provider off. The frontend server runs the same check at start.
- The proxy sets `Cache-Control: no-store` on every response in demo mode.
- **Rate limits live in the frontend server,** because the backend sees only the frontend's address. An in-memory token bucket per client address applies `DEMO_RATE_LIMIT` (requests per minute, default 60) to every request and `DEMO_NEW_SESSIONS_PER_HOUR` (default 5) to session starts. The client address is the socket address, or the last `X-Forwarded-For` hop when `TRUSTED_PROXY=true`. In-memory limits are why demo mode runs one frontend instance, which the demo compose overlay and the docs state.
- The demo overlay (`docker-compose.demo.yml`) sets `AUTH_MODE=demo`, puts Postgres and Chroma data on `tmpfs`, and sets no replicas.

### 10. Allow-list

`AUTH_ALLOWED_EMAILS` is a comma-separated list of addresses and `@domain` entries, compared case-insensitively. When set, the backend refuses a user whose token lacks `email`, or whose `email_verified` is not `true`, or whose address does not match, with `403 not_allowed`, before creating a user row. The frontend server runs the same check in the callback so the user sees a clear page, but the backend is the one that enforces it. In `oidc` mode the scopes must include `email`, which the default does.

### 11. Settings

| Setting | Modes | Default |
|---|---|---|
| `AUTH_MODE` | all | none, required |
| `SESSION_SECRET` | all (frontend) | none, required |
| `APP_BASE_URL` | all (frontend) | kept |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | oidc | required |
| `OIDC_SCOPES` | oidc | `openid email profile offline_access` |
| `OIDC_INTERNAL_URL` | oidc | unset |
| `FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN` | firebase | required |
| `AUTH_ALLOWED_EMAILS` | oidc, firebase | unset (anyone the provider logs in) |
| `DEMO_SESSION_TTL_HOURS` | demo | 24 |
| `DEMO_KEY_TTL_MINUTES`, `DEMO_KEY_MAX_HOURS` | demo | 30, 4 |
| `DEMO_RATE_LIMIT`, `DEMO_NEW_SESSIONS_PER_HOUR`, `DEMO_MAX_SESSIONS` | demo | 60, 5, 500 |
| `TRUSTED_PROXY` | demo | false |

`AUTH0_*` settings are removed from `.env.example` and `Settings`.

### 12. Pocket ID compose overlay

`docker-compose.pocket-id.yml` adds a pinned Pocket ID service with its data under `.data/pocket-id`, and sets `OIDC_INTERNAL_URL` to its compose address. Pocket ID logs in with passkeys only, and browsers allow passkeys only in a secure context: `localhost` works, a plain-HTTP LAN address does not. The docs say to put an HTTPS reverse proxy in front for LAN use, with a Caddy example.

### 13. New error codes

`not_allowed` (403), `demo_session_expired` (401), `demo_full` (503), and `rate_limited` (429, with `Retry-After`). `unauthenticated` and `service_unavailable` keep their meaning. The frontend adds the codes to `ApiErrorCode` with a page or message for each.

## Risks / Trade-offs

- [A provider does not send `email_verified`, so an allow-list shuts everyone out] → Task 1.1 probes Pocket ID. The failure is closed and the refusal page names the reason, so it is found at once. Without an allow-list the provider's own access rules apply.
- [ID tokens are meant for the client, not an API] → The frontend server and the backend are one application behind one client id, and the backend is not reachable from outside. The audience check still pins the token to this client.
- [Firebase tokens pass through browser JavaScript during sign-in] → In-memory persistence and an immediate sign-out leave no copy. This is the one documented exception to the token rule.
- [No revocation check for Firebase ID tokens] → Tokens live 1 hour. Revoking a user in Firebase stops renewal, so access ends within the hour.
- [An XSS bug in demo mode] → Keys and the session are in HttpOnly cookies, so a script can act as the visitor while the page is open but cannot take the key away.
- [Demo data on `tmpfs` uses RAM] → `DEMO_MAX_SESSIONS` and the per-address session limit bound it, and expiry frees it.
- [In-memory rate limits reset on restart and do not work with several instances] → Demo mode is one instance by design. A restart also wipes the demo data.
- [Large OIDC tokens overflow a cookie] → The sealed cookie is chunked.

## Migration Plan

1. Build after `model-providers` and `conversation-agent` have landed.
2. Ship the migration, backend, and frontend together: the credential the proxy sends changes type.
3. Set `AUTH_MODE` and the mode's settings in `.env` before starting. The server refuses to start without them, which makes a forgotten setting obvious.
4. The developer's existing user row becomes `auth0-legacy`. Log in again and re-enter the provider key, or reset the local database.
5. Rollback: `alembic downgrade -1` deletes every user whose issuer is not `auth0-legacy` (their data cascades), then restores `auth0_sub`. The previous images restore the Auth0 SDK.

## Open Questions

- Which Pocket ID version to pin. Decided when the overlay is written, from its current release.
