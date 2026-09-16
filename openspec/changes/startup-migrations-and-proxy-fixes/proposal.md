## Why

The `platform-foundation` Migration Plan says "Run `docker compose up`. The backend runs `alembic upgrade head` on startup", but nothing ever ran it: the backend container starts uvicorn directly, so a fresh stack comes up with an empty database and every request that touches a table fails. A code review of the Next.js API proxy also found three low-severity defects left over from the same change. All four are small, share the same surfaces (the backend container and `frontend/app/api/[...path]/route.ts`), and are cheaper to fix now than after `gate-framework` and `thought-storage` add tables and path-parameter endpoints on top of them.

## What Changes

- Apply Alembic migrations before the backend serves traffic, so a fresh `docker compose up` produces a usable schema. Applying migrations again when the database is already at head is a no-op, and a failed migration stops the container instead of starting a server against a half-built schema.
- Fix the API proxy's path-segment check, which decodes segments that Next.js has already decoded. A literal `%` in a segment (from `%25` in the URL) is not decodable a second time, so a path such as `/api/thoughts/100%25` is rejected with 404 instead of being forwarded. The check moves to the segment as Next.js passes it, with the second decode kept only as defense in depth for segments that are still decodable.
- Fix backend redirects, which reach the browser broken. The proxy fetches with `redirect: "manual"` and `location` is not in the response header allowlist, so an upstream 3xx becomes a redirect response with no target. An upstream 3xx now becomes 502 `backend_unreachable` with a server-side log that contains no access token.
- Document the proxy's `target.origin !== base.origin` guard as defense in depth. It is unreachable through the handler's own inputs, so it gets a comment rather than a test that would have to weaken the surrounding checks to reach it.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- None.

No spec-level behavior changes, so this change sets `skip_specs: true` in its `.openspec.yaml`:

- **Migrations on startup** is deployment mechanics. Neither spec says anything about how the schema is created; `user-auth`'s "Unauthenticated health check" requirement distinguishes only a reachable from an unreachable database, and a reachable database with no tables already answers `SELECT 1`, so that requirement's scenarios keep their current outcomes.
- **The `%` fix** changes no specified behavior. Neither spec constrains which path segments the proxy accepts, and the endpoints that exist today (`/api/me`, `/api/settings/api-key`) have no path parameters, so no scenario in either spec exercises the broken case. `user-auth`'s "Browser never holds the access token" requirement keeps its meaning unchanged: the request still goes to the frontend's own origin and is still forwarded with the user's token.
- **The redirect fix** reuses the existing `backend_unreachable` code from `platform-foundation` design decision 8. That code is a design-level decision and appears in neither spec, so no specified error behavior changes.
- **The origin comment** is a comment.

Inventing a requirement to make `openspec validate` accept a delta would put implementation mechanics into a behavior contract, so none is added.

## Impact

- **Modified code:** `backend/Dockerfile`, a new `backend/docker-entrypoint.sh`, `frontend/app/api/[...path]/route.ts`.
- **New tests:** `backend/tests/test_entrypoint.py`, plus cases in `frontend/app/api/[...path]/route.test.ts`.
- **Changed test:** the proxy's `malformed encoding` rejection case. A segment that cannot be decoded is no longer rejected, because that is exactly the case the `%` bug is. The segment is re-encoded before it reaches the backend, so it stays inside `/api/` on the backend origin. Every traversal case keeps rejecting.
- **New dependencies:** none. Alembic is already a backend dependency.
- **Configuration:** none. The entrypoint reads the `DATABASE_URL` that `alembic/env.py` already reads.
- **Not affected:** the backend test suite, which builds its schema with `Base.metadata.create_all` and never runs the entrypoint.
