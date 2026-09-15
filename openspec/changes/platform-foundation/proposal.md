## Why

Focus Funnel is a hosted, multi-user chatbot for brain dumping, where each user brings their own Nebius API key. Every later feature (gates, thought storage, /push, /pull, /explore) needs a running app, a logged-in user, and a safely stored key. The repository has no application code yet, so this foundation comes first.

## What Changes

- Create the project layout: a Next.js app in `frontend/`, a FastAPI app in `backend/`, and a docker-compose setup that runs both with Postgres and ChromaDB for local development.
- Add login and logout through Auth0 (free tier) in the Next.js app.
- Route every browser API call through Next.js server route handlers. The handlers attach the Auth0 access token on the server and forward the call to FastAPI. The browser never holds the access token, and FastAPI is not called directly from the browser.
- FastAPI checks every Auth0 access token (signature, issuer, audience, expiry). It creates a user record on the first authenticated request, keyed by the Auth0 subject (`sub`).
- Users can save, replace, and delete their Nebius API key. The backend checks the key against Nebius before it saves the key. It stores the key encrypted and shows only the last 4 characters.
- Add a settings page with an API key section. The gate-framework change adds gate model settings to this page later.
- Add a health endpoint for local and deployment checks.

## Capabilities

### New Capabilities
- `user-auth`: Login and logout, checks on access tokens, user records created on first request, and the rule that API access goes through the server-side proxy only.
- `nebius-api-key`: Bring-your-own Nebius API key. Users can save, check, mask, replace, and delete it, and it is stored encrypted.

### Modified Capabilities
- None. No specs exist yet.

## Impact

- **New code:** `frontend/` (Next.js), `backend/` (FastAPI), `docker-compose.yml`, Alembic migrations.
- **New dependencies:**
  - Frontend: Next.js and `@auth0/nextjs-auth0`.
  - Backend: FastAPI, SQLAlchemy, Alembic, a Postgres driver, `cryptography`, a JWT/JWKS library, `httpx`, and the `openai` SDK (Nebius has an OpenAI-compatible API).
- **External services:** an Auth0 tenant with one Application (Next.js) and one API (FastAPI audience), and the Nebius API.
- **Configuration:** Auth0 settings, `DATABASE_URL`, `KEY_ENCRYPTION_KEY`, `NEBIUS_BASE_URL`, `CHROMA_URL`.
- **Unblocks:** `gate-framework`, `thought-storage`, `push-and-pull-gates`, `explore-gate`.
