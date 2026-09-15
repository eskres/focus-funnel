## 1. Repository and local environment

- [x] 1.1 Create the `frontend/` (Next.js App Router, TypeScript) and `backend/` (FastAPI, Python 3.12+) projects from design decision 1, and check that `npm run build` and `python -c "import app.main"` both succeed
- [x] 1.2 Add `docker-compose.yml` with `frontend`, `backend`, `postgres`, and `chroma` services on pinned images, with only `frontend` publishing a host port. Check that `docker compose up` starts all 4 services and the frontend loads at its host port
- [x] 1.3 Add `docker-compose.dev.yml` that also publishes the backend port. Check that FastAPI docs load at `/docs` when both compose files are used
- [x] 1.4 Add `.env.example` listing the Auth0 settings, `AUTH0_AUDIENCE`, `DATABASE_URL`, `KEY_ENCRYPTION_KEY`, `NEBIUS_BASE_URL`, `CHROMA_URL`, and `BACKEND_URL`, each with a comment. Check the current Nebius base URL and add it as the example value
- [x] 1.5 Extend the root `.gitignore` (which already ignores `.env` files and `.claude/settings.local.json`) with `node_modules/`, `.next/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, and the local Chroma and Postgres data folders, and check with `git check-ignore` on one sample path for each entry

## 2. Backend core

- [x] 2.1 Add backend settings loading that fails at startup when a required variable is missing or `KEY_ENCRYPTION_KEY` is not 32 bytes of base64, and check it with a pytest test for each failure case
- [x] 2.2 Set up async SQLAlchemy (`asyncpg` and `aiosqlite`) and Alembic, and check that `alembic upgrade head` runs on an empty Postgres database and an empty SQLite database
- [x] 2.3 Add the shared error format and handlers (`unauthenticated`, `validation_error`, `not_found`, and the Nebius codes), and check with pytest that a validation failure and an unknown route both return `{ "error": { "code", "message" } }`
- [x] 2.4 Add `GET /health` with a database check, and check with pytest that it returns 200 `ok` with the database available and 503 when the database session fails

## 3. Login and user records

- [x] 3.1 Add the `users` table model and migration (`id`, unique `auth0_sub`, `created_at`), and check that the migration applies and the unique constraint rejects a duplicate `auth0_sub`
- [x] 3.2 Add the token check with PyJWT and a cached JWKS (RS256, issuer, audience, expiry, refetch on an unknown key id, 503 when no key is available), with a test JWKS based on a local RSA key pair. Check with pytest tests for a missing token, an expired token, the wrong audience, the wrong issuer, a bad signature, and a valid token
- [x] 3.3 Add the `current_user` dependency that creates the user record with an upsert, and check with pytest that the first request creates one record, repeat requests reuse it, and two requests at the same time for a new subject leave exactly one record
- [x] 3.4 Add `GET /api/me`, and check with pytest that it returns the user's `id` with a valid token and 401 without one
- [x] 3.5 Add an ownership helper that returns `not_found` for records owned by another user, and check it with a pytest test that uses a small test-only model

## 4. Nebius API key

- [x] 4.1 Add `crypto.py` with AES-256-GCM encryption that binds each key to its `user_id`, and check with pytest that a round-trip works, a ciphertext with a different `user_id` fails to decrypt, and two encryptions of the same key give different ciphertexts
- [x] 4.2 Add the `nebius_api_keys` table model and migration (unique `user_id`, `ciphertext`, `nonce`, `key_version`, `last4`, timestamps), and check that the migration applies and a second row for the same user is rejected
- [x] 4.3 Add `nebius.py` with `client_for(user)`, the key check through `models.list()` with a 10-second timeout, and the mapping from SDK errors to `nebius_key_invalid`, `nebius_unreachable`, `nebius_key_rejected`, and `nebius_key_missing`. Check each mapping with a pytest test against a mocked Nebius API
- [x] 4.4 Add `GET`, `PUT`, and `DELETE /api/settings/api-key`, and check with pytest the scenarios for a valid key, an invalid key, Nebius unreachable, an empty key, a valid replacement, an invalid replacement that keeps the old key, deletion, and a status response that shows only `last4`
- [x] 4.5 Add a log filter that masks API keys and skip request-body logging on the key endpoint, and check with a pytest test that captures logs during save and check that the full key never appears
- [x] 4.6 Check with a pytest test that reads the stored database row after a save that the row contains no plain-text key

## 5. Frontend login and proxy

- [x] 5.1 Set up Auth0 by hand: create the tenant, a Regular Web App, and an API with an identifier, then fill in the Auth0 values in `.env`. Check that `.env` has every Auth0 variable listed in `.env.example`
- [ ] 5.2 Add the Auth0 Next.js SDK with middleware that protects everything except `/`, configured with the API audience. Check by hand that opening `/app` while logged out redirects to Auth0, logging in returns to `/app`, and logging out ends the session
- [x] 5.3 Add the catch-all `app/api/[...path]/route.ts` proxy that attaches the access token on the server, forwards method, path, query, and body to `BACKEND_URL`, and streams the response body unbuffered. Check with Vitest that it forwards the token and returns 401 `unauthenticated` without calling the backend when there is no session
- [x] 5.4 Add a Vitest test for the proxy that sends a backend stream in parts with delays, and check that the parts reach the client one at a time
- [ ] 5.5 Check in browser dev tools, after logging in, that no response body and no cookie readable by JavaScript contains the access token
- [x] 5.6 Add a typed fetch helper that converts the error format into typed errors, and check with Vitest that `nebius_key_missing` and `unauthenticated` responses become the matching error types

## 6. Frontend pages

- [x] 6.1 Add Tailwind CSS v4 and run `npx shadcn@latest init` in `frontend/`, remove the starter `page.module.css` styles, and add the `button`, `input`, `card`, and `alert` components. Check that `npm run build` passes and a shadcn `Button` renders on `/`
- [x] 6.2 Add the `/` landing page with a shadcn `Button` for login and the `/app` placeholder page, and check that `/` loads while logged out and `/app` shows the placeholder while logged in
- [ ] 6.3 Add the `/settings` API key section with shadcn `Card`, `Input`, `Button`, and `Alert` (no-key state with an input, saved state with `last4` and the save date, replace, delete), and check by hand with a real Nebius key and a fake key that each state and each error message appears as the spec describes
- [x] 6.4 Add a shared component built on shadcn `Alert` that shows `nebius_key_missing` and `nebius_key_rejected` messages with a link to `/settings`, and check with a Vitest render test that each message and link appears

## 7. Full system check

- [x] 7.1 Run the backend test suite on SQLite and on the compose Postgres, and check that both pass
- [ ] 7.2 On a fresh `docker compose up`, run the full flow (log in, open settings, save a valid key, see `last4`, replace it with an invalid key and see the old key kept, delete the key, log out), and check that each step matches the specs
- [ ] 7.3 Check that the backend port is not published by the default `docker-compose.yml`: a request to the backend from the host fails, and the same call through the frontend proxy succeeds
