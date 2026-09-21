> **Planning status:** Proposal only. Write the specs, design, and tasks when this change is picked up. Depends on `platform-foundation` and `model-providers`.

## Why

Login is hard-wired to Auth0. Its hosted login page does not suit an open-source, self-hosted project: every self-hoster would need an Auth0 tenant, and the page is not ours to design. A self-hoster needs a choice of login that can run without a big service, a public web deployment needs its own option, and a public demo needs to let strangers try the app without accounts and without their data or keys lingering. The `user-auth` requirements already say the browser never holds the access token, and that rule stays.

## What Changes

- Add `AUTH_MODE` in `.env` with three values, and remove the Auth0 dependency, settings, and hosted login routes:
  - `oidc`: log in through any OpenID Connect provider. Pocket ID is the documented lightweight choice, and it can run as an optional compose service. Authentik, Keycloak, and Auth0 work the same way through the same settings.
  - `firebase`: log in through a Firebase project, for anyone hosting the app on the web.
  - `demo`: no login, for a public demo instance.
- Give the backend one step that turns a request into the current user, with one implementation per mode. Everything after it (ownership checks, user records) is unchanged.
- In `oidc` and `firebase` modes, keep tokens on the server. The Next.js server runs the login flow and holds the session in an HttpOnly cookie, and the backend verifies the token against the provider's published keys (issuer and audience for `oidc`, the project id for `firebase`).
- Let an operator limit who may sign in with an optional email allow-list, in both real modes. In `oidc` mode the provider's own access rules also apply.
- In `demo` mode:
  - Each visitor gets an anonymous user behind a random, unguessable session cookie (128 bits or more, HttpOnly, Secure). Every read and write is scoped to that user, so another visitor's conversation returns 404 even with its URL.
  - Anonymous users and everything they own are deleted after a set time. A background task removes them, and the demo compose overlay runs Postgres on a temporary file system so nothing survives a restart.
  - API keys are not stored on the server. The browser keeps a key for a short time (30 minutes idle and a 4 hour limit by default), sends it with each request, and the server uses it for that call only and never logs it. A "forget key" button clears it at once.
  - Custom provider URLs are turned off, so the server cannot be pointed at internal addresses.
  - Responses are marked `no-store`, a per-IP rate limit applies, and only one instance runs.
  - A notice is shown before the first message, saying what is stored, for how long, that the operator can technically read stored chats, and what the chosen provider does with prompts. It reuses the provider's own notice text.
  - The server refuses to start in `demo` mode if `oidc` or `firebase` settings are also present.
- Settings for demo mode: `DEMO_KEY_TTL_MINUTES`, `DEMO_KEY_MAX_HOURS`, `DEMO_SESSION_TTL_HOURS`, and `DEMO_RATE_LIMIT`.
- There is no mode with no login and persistent data. Self-hosters choose `oidc` or `firebase`, or run demo mode for a throwaway instance.

## Capabilities

### New Capabilities

- `auth-modes`: Choosing the mode, `oidc` and `firebase` login, the email allow-list, and the rule that tokens stay on the server.
- `demo-mode`: Anonymous sessions, isolation between visitors, expiry, keys held in the browser, the notice, and the guards.

### Modified Capabilities

- `user-auth`: Login is no longer through Auth0. The backend accepts a valid token from the configured mode's provider, and the user record is created once per provider subject.
- `provider-keys`: In demo mode a key comes with the request and is not stored.

## Impact

- **Backend:** an `authenticate(request)` step with three implementations; settings for each mode and startup checks; an anonymous user record with an expiry, and a cleanup task; token verification for OIDC and Firebase; the request-supplied key path; response headers and the rate limit in demo mode.
- **Frontend:** a login flow per mode, replacing the Auth0 SDK and its `/auth/*` routes served by `proxy.ts`; the demo notice; the key holder with its expiry and "forget key" button.
- **Deployment:** an optional compose service for Pocket ID and a demo overlay with Postgres on a temporary file system.
- **Dependencies:** removes `@auth0/nextjs-auth0`. Adds a generic OIDC client library and the Firebase web SDK, with token verification for Firebase on the backend.
- **Open questions for when it is picked up:** whether Pocket ID's passkey-only login needs a secure context (HTTPS or localhost) on a plain-HTTP LAN, which token the backend verifies in `oidc` mode, and whether the Firebase session cookie needs a service account.
