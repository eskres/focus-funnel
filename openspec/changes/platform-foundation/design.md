## Context

The repository has no application code yet. The target stack is fixed:

- Frontend: Next.js (App Router)
- Backend: FastAPI
- App data: Postgres with SQLAlchemy
- Vectors: ChromaDB
- Login: Auth0 (free tier)
- Models: the Nebius API, with each user's own key

For motivation and scope, see `proposal.md`. For the required behavior, see `specs/user-auth/spec.md` and `specs/nebius-api-key/spec.md`.

Two constraints from later changes shape this design:

- Every later change needs a user id, and every Nebius call needs that user's decrypted key.
- The backend must not be reachable from the browser (see decision 2).

## Goals / Non-Goals

**Goals:**
- Build a skeleton that runs locally with one `docker compose up`.
- Put the patterns in place for login, user records, error responses, and Nebius client creation, so later changes reuse them unchanged.
- Store keys in a way that allows master key rotation later without changing the schema.

**Non-Goals:**
- Choosing where the app is deployed, and deployment config.
- A tool to rotate the master key. The schema only stores a key version.
- Account deletion. The `thought-storage` change adds it.
- End-to-end browser tests.
- Setting up Auth0 login methods (email and password, social). That's done in the Auth0 dashboard, not in code.

## Decisions

### 1. Monorepo layout

```
focus-funnel/
+-- frontend/            Next.js App Router, TypeScript
+-- backend/
|   +-- app/
|   |   +-- main.py      FastAPI app, routers, error handlers
|   |   +-- auth.py      token check + current_user dependency
|   |   +-- db.py        engine, session, Base
|   |   +-- models/      SQLAlchemy models
|   |   +-- crypto.py    key encryption
|   |   +-- nebius.py    client factory + error mapping
|   |   +-- routers/     me, api_key, health
|   +-- alembic/
|   +-- tests/
+-- docker-compose.yml
+-- docker-compose.dev.yml
+-- .env.example
```

One repository keeps the API contract and the planning artifacts in one place. **Alternative:** separate frontend and backend repositories. Rejected because it adds overhead for a single small team.

### 2. Next.js server acts as a proxy for all API calls

```
 browser --(cookie session)--> Next.js /api/[...path] route handler
                                   | getAccessToken() on the server
                                   v
                               FastAPI (private network)
```

- A single catch-all route handler (`frontend/app/api/[...path]/route.ts`) forwards the method, path, query, and body to `BACKEND_URL`.
- It adds `Authorization: Bearer <token>`, using the access token it gets from the Auth0 Next.js SDK.
- It returns the backend's response body as a `ReadableStream`, without buffering, so the SSE streams in later changes work unchanged.
- The Auth0 SDK's own routes (login, logout, callback) are handled by the SDK and are not forwarded.
- The Auth0 client requests the configured API `audience`, so the access token is a JWT that FastAPI can check.

**Alternative:** the browser calls FastAPI directly with a bearer token. Rejected: the token would live in browser JavaScript, FastAPI would have to be public, and CORS config would be needed.

### 3. FastAPI token check with PyJWT and a cached JWKS

- A `current_user` dependency does four things:
  1. Reads the bearer token.
  2. Checks it with `PyJWKClient` against `https://<AUTH0_DOMAIN>/.well-known/jwks.json`.
  3. Requires the `RS256` algorithm, `iss = https://<AUTH0_DOMAIN>/`, `aud = AUTH0_AUDIENCE`, and a valid `exp`.
  4. Returns the user record.
- Signing keys are cached. If a token names a key id that isn't in the cache, the JWKS is fetched again, at most once per minute. If the JWKS can't be fetched and the cache holds no matching key, the request fails with HTTP 503. It does not fail with 401, because the token may be fine.
- Tests replace the JWKS source with a local RSA key pair, so they don't need Auth0.

**Alternatives:** `python-jose` (less actively maintained), and Auth0's token introspection over the network (adds a network call to every request). Both rejected.

### 4. User record created with an upsert

- `users` table columns: `id` (UUID, primary key), `auth0_sub` (unique, not null), `created_at`.
- `current_user` runs `INSERT ... ON CONFLICT (auth0_sub) DO NOTHING` and then a `SELECT`. The same statement works on Postgres and SQLite, and it meets the "two first requests" scenario without an app-level lock.
- Email is not stored. Access tokens don't include it by default, and nothing needs it yet.
- Every later user-owned table gets a foreign key to `users.id`.

### 5. Database access: async SQLAlchemy 2.0 and Alembic

- The database layer uses async SQLAlchemy with `asyncpg` for Postgres, and `aiosqlite` for the SQLite test suite.
- FastAPI endpoints are async, and the later SSE endpoints need async code anyway.
- Alembic manages every schema change from the first migration.
- Postgres from docker-compose is the default development database. SQLite runs the fast unit tests. A Postgres test job runs the same suite, which catches differences between the two databases.

**Alternative:** sync SQLAlchemy. Rejected because streaming endpoints would need thread pools.

### 6. Key encryption: AES-256-GCM, bound to the user

`nebius_api_keys` table (one row per user):

```
id | user_id (unique FK) | ciphertext | nonce | key_version | last4 | created_at | updated_at
```

- Encryption uses `cryptography`'s `AESGCM` class with a random 96-bit nonce for every write.
- The associated data is `user_id`. A ciphertext copied onto another user's row fails to decrypt, which covers the "record copied to another user" scenario.
- The master key comes from the `KEY_ENCRYPTION_KEY` env var: 32 random bytes, base64-encoded. The app fails at startup if the key is missing or the wrong length.
- `key_version` is `1` for now. A later rotation tool can add more versioned master keys and re-encrypt rows without a schema change.
- `last4` is stored separately, so the status endpoint never decrypts the key.

**Alternative:** Fernet. Simpler, but it has no associated data, so user binding would need extra code. Rejected.

### 7. Nebius client factory and key check

- `nebius.py` exposes `client_for(user)`. It loads and decrypts the user's key and returns an `openai.AsyncOpenAI(base_url=NEBIUS_BASE_URL, api_key=...)` client for a single request. Clients are never cached across users.
- To check a key, the backend calls `client.models.list()` with a 10-second timeout:
  - Nebius returns 401 or 403: error code `nebius_key_invalid`.
  - Timeout, connection error, or 5xx: error code `nebius_unreachable`.
- One error-mapping function converts OpenAI SDK errors into the spec error codes. `nebius_key_rejected` covers a saved key that fails during use. Later gate changes reuse this function.
- Log messages pass through a filter that masks anything that looks like the current key. The API key endpoint also never logs request bodies.
- `NEBIUS_BASE_URL` is configuration, not a constant. The correct Nebius base URL must be checked when setting up the environment.

### 8. API shape and error format

Endpoints:

```
GET    /health                    no auth
GET    /api/me                    { id, created_at }
GET    /api/settings/api-key      { saved: bool, last4?, saved_at? }
PUT    /api/settings/api-key      body { api_key } -> same shape as GET
DELETE /api/settings/api-key      204
```

Every error uses the same format:

```json
{ "error": { "code": "nebius_key_invalid", "message": "Nebius rejected this API key." } }
```

The codes in this change are `unauthenticated`, `validation_error`, `not_found`, `nebius_key_missing`, `nebius_key_invalid`, `nebius_key_rejected`, and `nebius_unreachable`. The frontend maps codes to UI; for example, `nebius_key_missing` shows a link to settings. Later changes add codes and keep the format.

Requests for another user's record return `not_found`, as the spec requires.

### 9. Local environment with docker-compose

- `docker-compose.yml` runs four services: `frontend`, `backend`, `postgres`, and `chroma`, with pinned image versions.
- Only `frontend` publishes a host port. `backend` is reachable only on the compose network, which matches the proxy rule.
- `docker-compose.dev.yml` also publishes the backend port for local debugging and the FastAPI docs.
- ChromaDB is included now, so later changes don't need to change the compose file, but nothing uses it yet.
- `.env.example` lists every variable, with comments.

### 10. Frontend structure

- The Auth0 Next.js SDK middleware protects every route except the public landing page (`/`).
- Pages: `/` (landing with a login button), `/app` (an empty chat placeholder that `gate-framework` fills in), `/settings` (the API key section).
- A small typed fetch helper calls `/api/...` and turns the error format into typed errors.
- Checks: TypeScript type checks, ESLint, and Vitest tests for the proxy handler and the fetch helper.

## Risks / Trade-offs

- [Auth0 free tier limits or terms change] → The backend only checks standard OIDC JWTs through a JWKS URL. Moving to another OIDC provider means changing config and replacing the frontend SDK, not rewriting the backend.
- [Lost or leaked `KEY_ENCRYPTION_KEY`] → If lost, stored keys can't be decrypted and users must re-enter their Nebius keys. Thoughts are not affected. If leaked, keys can be decrypted by anyone with the database. Mitigation: keep the master key out of the database host's environment where possible, and plan the rotation tool before production use.
- [SQLite and Postgres behave differently] → Use portable SQL only, and run the test suite on both databases.
- [The proxy buffers streamed responses] → Return a `ReadableStream`, set `Cache-Control: no-cache`, and set `X-Accel-Buffering: no`. A proxy test checks that stream parts arrive one at a time.
- [Auth0 JWKS outage] → Cached signing keys keep existing sessions working. Only tokens signed with a new key fail, and those fail with 503, not 401.
- [Nebius key check calls add delay to saving] → They happen only on save and replace, with a 10-second timeout.

## Migration Plan

The project has no users and no data yet, so there is nothing to migrate. Setup steps:

1. Create the Auth0 tenant, an Application (Regular Web App), and an API with an identifier.
2. Copy `.env.example` to `.env`. Fill in the Auth0 values, `KEY_ENCRYPTION_KEY`, and `NEBIUS_BASE_URL`.
3. Run `docker compose up`. The backend runs `alembic upgrade head` on startup.

Rollback: `alembic downgrade base` removes the tables in this change.

## Open Questions

- Which login methods to turn on in Auth0 (email and password, Google, GitHub). This is dashboard config only.
- The current Nebius API base URL and the model listing response. Check both when writing `.env.example`. Only config changes.
