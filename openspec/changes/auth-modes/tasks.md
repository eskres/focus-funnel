## 1. Probes

- [x] 1.1 Run Pocket ID locally from its current release, register a client, and log in once with a passkey on `localhost`. Check by recording in `design.md` decisions 5 and 12 the pinned version, whether the ID token carries `email` and `email_verified`, its signing algorithm, whether `offline_access` gives a refresh token, and whether discovery works through `OIDC_INTERNAL_URL` from a container
- [x] 1.2 Create a Firebase test project with Google and email-and-password sign-in, sign in from a scratch page with `inMemoryPersistence`, and renew the token through the securetoken endpoint with only the web API key. Check by recording in `design.md` decision 6 that renewal works without a service account and the ID token's `iss`, `aud`, and algorithm

## 2. Settings and startup checks

- [x] 2.1 Replace the Auth0 fields in the backend `Settings` with `auth_mode` and the per-mode settings from design decision 11, with the demo guards from decision 9. Check with pytest that a missing or unknown mode fails naming the setting, that each mode fails without its required settings, that demo mode fails with an `OIDC_*` or `FIREBASE_*` value or an explicit `ALLOW_CUSTOM_PROVIDER=true`, and that demo mode otherwise turns the custom provider off
- [x] 2.2 Add `lib/auth-mode.ts` with the same checks for the frontend server, read at run time. Check with Vitest that each invalid configuration throws naming the setting and that no `NEXT_PUBLIC_` variable carries the mode
- [x] 2.3 Update `.env.example` for the three modes and remove every `AUTH0_*` entry. Check by reading it against design decision 11

## 3. Data

- [ ] 3.1 Add one migration that renames `users.auth0_sub` to `subject`, adds `issuer` (existing rows `auth0-legacy`), `expires_at`, and `demo_notice_accepted_at`, and swaps the unique index to `(issuer, subject)`. Check that `alembic upgrade head` then `downgrade -1` runs cleanly on an empty SQLite database and on the compose Postgres, that an existing row survives as `auth0-legacy`, and that there is a single Alembic head
  - Postgres check not run: no Docker. The SQLite check passed: `alembic upgrade head` then `downgrade -1` on an empty database, an existing row survives as `auth0-legacy`, and there is a single Alembic head (`tests/test_auth_modes_migration.py`).
- [x] 3.2 Change `get_or_create_user` to take an issuer and subject. Check with pytest that two concurrent first requests create one row, and that the same subject from two issuers creates two users who cannot see each other's records
- [x] 3.3 Add `delete_user_data(user)` that deletes the user and everything that cascades from it. Check with pytest that after it runs no row for that user remains in any user-owned table and another user's rows are unchanged

## 4. Backend authentication

- [x] 4.1 Add the `authenticate` step and `Identity`, pick the authenticator from the mode at startup, and move `get_current_user` onto it. Check with pytest that routers and ownership tests pass unchanged
- [x] 4.2 Add `OidcAuthenticator`: discovery (through `OIDC_INTERNAL_URL` when set), `JwksCache`, and ID token checks. Check with pytest and a local signing key for a valid token, missing, expired, wrong issuer, wrong audience, bad signature, `HS256`, and `none` tokens, and a JWKS outage giving `503 service_unavailable`
- [x] 4.3 Add `FirebaseAuthenticator` against Google's key set. Check with pytest and a local signing key for a valid token, a token from another project, and an expired token
- [x] 4.4 Add the allow-list with addresses and `@domain` entries. Check with pytest that a listed address and a listed domain get in, that an unlisted or unverified address or a missing `email` claim gives `403 not_allowed` with no user row created, and that no list lets anyone in
- [x] 4.5 Add the error codes `not_allowed`, `demo_session_expired`, `demo_full`, and `rate_limited`. Check with pytest that each constructor returns its documented status

## 5. Backend demo mode

- [x] 5.1 Add `POST /api/demo/sessions`, `DELETE /api/demo/session`, `POST /api/demo/notice`, and the mode, expiry, and notice fields on `GET /api/me`, present only in demo mode. Check with pytest that a session value has 32 random bytes, that only its hash is stored, that `DEMO_MAX_SESSIONS` gives `503 demo_full`, that ending a session deletes the user, and that the routes return 404 in other modes
- [x] 5.2 Add `DemoAuthenticator`. Check with pytest that a live value finds its user, that an expired one gives `401 demo_session_expired` before cleanup has run, and that a demo value is refused in `oidc` mode
- [x] 5.3 Add the cleanup task in the lifespan. Check with pytest that expired demo users and their data are deleted, that live and real users are untouched, and that the task keeps running after an error
- [x] 5.4 Read provider keys from `X-Provider-Keys` in demo mode behind `client_for()` and the provider list, and never write `provider_keys` there. Check with pytest that a key save in demo mode checks the key and writes no row, that the provider list reports held keys with last 4 characters and expiry, that the header is ignored in other modes, and that no log entry holds a full key
- [x] 5.5 Check isolation between visitors. Check with pytest that visitor A gets 404 for visitor B's conversation, settings, and usage

## 6. Frontend session and proxy

- [x] 6.1 Add `lib/session.ts` with the sealed, chunked `ff_session` cookie under `SESSION_SECRET`. Check with Vitest that a sealed cookie round-trips, that a tampered one is refused, that a large token is chunked and restored, and that the cookie is HttpOnly, Secure, and SameSite=Lax
- [x] 6.2 Replace `auth0.getAccessToken()` in the API proxy with `getBackendCredential()`, renewing tokens that expire within 60 seconds. Check with Vitest that a valid session forwards the ID token, that an expiring one is renewed first, that a failed renewal clears the cookie and gives 401 `unauthenticated` without calling the backend, and that the existing proxy tests pass
- [x] 6.3 Rewrite `proxy.ts` without the Auth0 middleware: public paths, login redirects per mode, and demo session start. Check with Vitest that a logged-out user on `/app` goes to `/auth/login` with `returnTo` in `oidc` mode and to `/login` in `firebase` mode, and that demo mode starts a session instead

## 7. OIDC login

- [x] 7.1 Add `/auth/login`, `/auth/callback`, and `/auth/logout` with `openid-client`, PKCE, state, and nonce. Check with Vitest against a mocked provider that a good callback starts a session and returns to `returnTo`, that a wrong state or nonce or a provider error shows the "login did not complete" page, and that logout clears the cookie and redirects to `end_session_endpoint` when present
- [x] 7.2 Add the "not allowed" page from the callback's allow-list check. Check with Vitest that an unlisted address sees it and gets no session

## 8. Firebase login

- [x] 8.1 Add the `/login` page with the Firebase web SDK, `inMemoryPersistence`, Google and email-and-password sign-in, and the hand-off to `/auth/firebase/session` followed by `signOut()`. Check with Vitest against a mocked SDK that the tokens are posted and sign-out is called, and that nothing is written to local or session storage
- [x] 8.2 Add `/auth/firebase/session` and renewal through the securetoken endpoint. Check with Vitest that a valid token starts a session, that a token from another project is refused, and that renewal replaces the token

## 9. Frontend demo mode

- [x] 9.1 Add the demo key cookie to the proxy as design decision 8 describes. Check with Vitest that a successful key save adds the key, that idle and maximum age drop it, that `DELETE` removes one key without calling the backend, and that no key appears in a response body or a readable cookie
- [x] 9.2 Add `Cache-Control: no-store` and the rate limits in demo mode. Check with Vitest that every response carries `no-store`, that requests past `DEMO_RATE_LIMIT` get `429 rate_limited` with `Retry-After`, that session starts past the hourly limit are refused, and that `X-Forwarded-For` is used only with `TRUSTED_PROXY=true`
- [x] 9.3 Add the demo notice, the expiry display, the "End demo" button, and the expired-session page. Check with Vitest that the composer is blocked until the notice is accepted, that the notice includes the provider's notice, that "End demo" asks before deleting, and that `demo_session_expired` shows the page with a "Start again" button
- [x] 9.4 Show a held key's expiry and a "Forget key" button on the provider cards in demo mode, and hide the custom card. Check with Vitest against mocked responses

## 10. Deployment and cleanup

- [x] 10.1 Remove `@auth0/nextjs-auth0`, `lib/auth0.ts`, and the Auth0 names in the backend, and add `openid-client`, `jose`, and `firebase`. Check that a search of `backend/` and `frontend/` for `auth0` finds only the `auth0-legacy` issuer and docs naming Auth0 as an `oidc` provider
  - The search also finds the old column name `auth0_sub` in the two Alembic migrations (`902d87703656` creates it, `a97e96671d5c` renames it) and in the migration tests that insert rows at those revisions. They are the history behind the `auth0-legacy` rows, which the user accepted as allowed on 2026-09-24.
- [x] 10.2 Add `docker-compose.pocket-id.yml` with the version from task 1.1 and `docker-compose.demo.yml` with `tmpfs` data and one instance. Check that `docker compose config` accepts both overlays
- [ ] 10.3 Write the login setup docs: Pocket ID, another OIDC provider, Firebase, the allow-list, HTTPS for passkeys on a LAN with a Caddy example, and demo mode with its guards. Check by following the Pocket ID section on a clean checkout
  - Walkthrough not run: needs Docker and a passkey. The docs are in `docs/login.md`, linked from the README.

## 11. Full system check

- [ ] 11.1 Run the backend suite on SQLite and on the compose Postgres, and `npm run test`, `npm run lint`, and `npm run build` in `frontend/`. Check that all pass
- [ ] 11.2 With the Pocket ID overlay, log in, chat, log out, and log in again. Check that the same user and data come back, that a token past its expiry is renewed without a login, and that an address off the allow-list sees the refusal page
- [ ] 11.3 With the Firebase test project, log in with Google and with email and password. Check that it works and that the browser's storage holds no Firebase token afterwards
- [ ] 11.4 With the demo overlay, open the app in two browsers. Check that each gets its own session, that one cannot open the other's conversation URL, that a saved key is forgotten after the idle time, that "End demo" deletes the data, and that a restart leaves no data
- [ ] 11.5 Start the server with each wrong configuration from task 2.1. Check that it refuses to start and names the setting
