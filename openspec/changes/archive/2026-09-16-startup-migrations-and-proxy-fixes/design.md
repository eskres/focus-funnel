## Context

See `proposal.md` - Why. Four defects, all inherited from `platform-foundation`, across two surfaces:

- The backend image (`backend/Dockerfile`) runs `CMD ["uvicorn", "app.main:app", ...]`. Alembic is installed and `backend/alembic/env.py` already reads `DATABASE_URL` from the environment, so the migration machinery works; nothing invokes it.
- The proxy handler (`frontend/app/api/[...path]/route.ts`) built by `platform-foundation` decision 2.

Constraints that shape the approach:

- The backend test suite builds its schema with `Base.metadata.create_all` against SQLite (`backend/tests/conftest.py`), never through Alembic, and it must stay that way: it is the fast suite.
- The proxy's existing guards are load-bearing and their tests are the record of what they guard. Rejecting `.`, `..`, empty segments, and segments holding `/` or `\` must keep working.
- `platform-foundation` decision 8 fixes the error-code set. Adding a code would be a spec-level change, so the redirect fix reuses one.

## Goals / Non-Goals

**Goals:**
- Migrations run exactly once per container start, before anything binds a port.
- Every failure mode is loud: a migration error stops the container with a non-zero exit.
- The proxy accepts the path segments Next.js actually hands it, including ones holding a literal `%`.
- No upstream response ever reaches the browser in a shape the browser cannot act on.

**Non-Goals:**
- Coordinating migrations across more than one backend replica. The compose stack runs one backend container; a multi-replica deployment would need a lock or a separate migration job, and that belongs with the deployment change.
- Making the backend test suite run migrations. A Postgres job that runs `alembic upgrade head` already exists as a task in `platform-foundation`.
- Adding redirect support to the API. The backend has no redirecting endpoint, and this change does not add one.

## Decisions

### 1. Migrations run from a container entrypoint, not from the app's lifespan

`backend/docker-entrypoint.sh` runs `alembic upgrade head` and then `exec "$@"`. The Dockerfile sets `ENTRYPOINT ["/srv/docker-entrypoint.sh"]` and keeps its existing `CMD`, so the command the container runs is unchanged and overridable.

```
docker-entrypoint.sh
  set -e
  alembic upgrade head      # fails -> script exits non-zero, no server starts
  exec "$@"                 # uvicorn replaces the shell as PID 1
```

Why the entrypoint over FastAPI's `lifespan`:

- **One run per container.** `lifespan` runs once per uvicorn worker. The image runs a single worker today, but `--workers N` is a one-flag change, and it would turn startup into N concurrent `alembic upgrade head` calls racing for the same `alembic_version` row.
- **Nothing is served against a partial schema.** The entrypoint finishes before uvicorn exists, so there is no window in which the port is open and the schema is not ready. A `lifespan` that migrated would hold the port open while migrating, and a `lifespan` that raised would leave uvicorn to decide the exit code.
- **The test suite is untouched by construction.** Tests import `app.main`, so anything in `lifespan` is something the tests must then work around. A shell script is not importable, so there is nothing to work around.
- **`exec` keeps signal handling correct.** uvicorn becomes PID 1 and receives `SIGTERM` from `docker stop` directly.

**Alternative: run migrations in `lifespan`.** Rejected for the four reasons above. **Alternative: a separate one-shot `migrate` compose service that `backend` depends on with `condition: service_completed_successfully`.** This is the cleanest answer for multi-replica deployments and is where this should go if the backend is ever scaled out. Rejected now because it adds a service and a second image invocation to the compose file for a single-container stack, and because it only moves the same command behind more configuration.

Idempotence and loudness come from Alembic itself: `upgrade head` compares `alembic_version` against the revision graph and does nothing when they match, and it exits non-zero on a failed migration. `set -e` turns that into a failed container start. The script needs no retry loop: compose already gates the backend on `postgres`'s `service_healthy` healthcheck.

### 2. The proxy checks the segment Next.js passes, and decodes only as defense in depth

Next.js has already percent-decoded each element of `params.path`. `isSafeSegment` decodes a second time and rejects the segment when that throws, which is what breaks a literal `%`: `decodeURIComponent("100%")` throws, so `/api/thoughts/100%25` is a 404.

The second decode is not what makes the check safe. Safety comes from the two facts either side of it: Next.js hands over a decoded segment, and `backendTarget` re-encodes every segment with `encodeURIComponent` before building the URL. So a segment is checked as-is, and the second decode is kept only for segments that are still decodable, where it catches a doubly-encoded traversal sequence such as `%2e%2e`:

```
values = [segment] + ([decodeURIComponent(segment)] if that succeeds else [])
reject if any value is "", ".", "..", or holds "/" or "\"
```

A segment that cannot be decoded is now checked on its own text instead of being rejected. That is a deliberate, narrow behavior change and the only test that changes: `%E0%A4%A` was rejected as `malformed encoding` and is now forwarded as `%25E0%25A4%25A`. It is the same case as `100%` - a `%` that starts no valid escape - and there is no rule that separates them, because both fail `decodeURIComponent` for the identical reason. Forwarding it is safe: `encodeURIComponent` escapes the `%`, so the segment reaches the backend as one opaque path component inside `/api/` on the backend origin, and the backend answers 404 for a path it does not serve. The test moves from the rejection table to a case asserting it is forwarded encoded, so the behavior stays pinned either way.

Every traversal case still rejects, through one branch or the other: `..`, `.`, `""`, `a/b` and `a\b` on the raw segment; `%2e%2e`, `.%2e`, `..%2F..%2Fhealth` and `a%5Cb` on the decoded one.

**Alternative: stop decoding entirely.** Simpler, and arguably correct given the re-encoding, but it drops four existing test cases and their protection for anything that hands the handler a still-encoded segment. Rejected: the decode costs nothing where it applies.

### 3. An upstream 3xx becomes 502 `backend_unreachable`

The proxy fetches with `redirect: "manual"`, so a backend 3xx is returned rather than followed, and `location` is not in `FORWARDED_RESPONSE_HEADERS`, so the browser receives a redirect status with no target and stalls. The proxy now treats any upstream status in `300..399` as a failed call: it cancels the upstream body, logs the method, path, and status on the server, and returns 502 `backend_unreachable`.

Why this over rewriting a same-origin `Location` onto `/api/...`:

- **The API has no redirects.** `platform-foundation` decision 8 lists five endpoints, none of which redirect. An upstream 3xx therefore means a misconfiguration or an unexpected upstream, and reporting it as a failed backend call is the honest answer.
- **The header allowlist stays closed.** Rewriting means adding `location` to `FORWARDED_RESPONSE_HEADERS` and then relying on a parse-and-compare to keep a backend-controlled header from becoming an open redirect out of the frontend origin. That is a security-relevant code path added to serve a case that does not occur.
- **No new error code.** `backend_unreachable` already covers "the frontend could not complete the call to the backend", which is exactly what happened, and it is already the proxy's 502. Adding a code would be a spec-level change for a case users should never see.
- **It is visible.** The server-side log names the status, so a backend that starts redirecting shows up in logs instead of as a silently stalled browser.

The log reuses the existing shape from the fetch-failure branch, which logs only method and path - never the token, and never a header dump.

**Alternative: rewrite a same-origin `Location`.** Rejected for the reasons above. If the API ever gains a redirecting endpoint, this becomes the right change, and the 502's log is where that will first be noticed.

### 4. The origin guard gets a comment, not a test

`backendTarget` ends with `if (target.origin !== base.origin || !target.pathname.startsWith("/api/")) return null`. Neither half can be reached through the handler's inputs: `path` is built as the literal `"/api/"` followed by `encodeURIComponent`-escaped segments, and `new URL(path + search, base.origin)` resolves a path-absolute reference against `base.origin`, which cannot produce another origin. The test suite's `other host` case, `[".%2e", "", "127.0.0.1:9999", "steal"]`, is caught by the empty-segment rule before it ever gets there.

So the guard gets a comment saying it is defense in depth over the encoding above it, and no test. A test that reached it would have to be written against a weakened `backendTarget` - a second code path that exists only to be tested - and it would pin an internal detail rather than behavior. Deleting the guard was also considered and rejected: it is two cheap comparisons standing between a future edit to the path construction and a request leaving the backend origin, and it should outlive whoever remembers why the encoding is sufficient.

## Risks / Trade-offs

- [A future multi-replica backend runs concurrent migrations] → Out of scope by decision 1, and recorded there: the fix is a one-shot migration service, and the entrypoint's single command moves into it unchanged.
- [A long migration delays the container's readiness] → Accepted. The migrations in this project create tables on an empty database. A slow migration should be visible as a slow start, not hidden behind a server answering requests against a schema that is still changing.
- [An undecodable segment now reaches the backend] → Bounded by `encodeURIComponent`: it arrives as one opaque path component under `/api/` on the backend origin, which is the same guarantee every other segment has. Covered by a test asserting the forwarded path.
- [A genuine backend redirect would now surface as 502] → Intended, and logged with its status so it is diagnosable rather than silent. Decision 3 records the alternative to switch to.
- [The entrypoint is not executable in the image] → Guarded twice: the file is committed with its executable bit, and the Dockerfile sets it again with `chmod +x`, so a checkout that loses file modes still builds a working image.

## Migration Plan

No data migration and no configuration change. The entrypoint reads the `DATABASE_URL` the backend service already sets in `docker-compose.yml`.

Deploy: rebuild the backend image. The first start applies every pending migration; later starts are no-ops.

Rollback: the proxy changes revert on their own. For the backend, reverting the Dockerfile restores the direct `uvicorn` command, and the schema Alembic created stays as it is - `alembic downgrade` is not part of rolling this change back, because this change adds no migrations.

## Open Questions

None.
