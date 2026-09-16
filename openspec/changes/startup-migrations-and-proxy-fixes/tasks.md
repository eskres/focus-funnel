## 1. Migrations on backend startup

- [ ] 1.1 Add `backend/docker-entrypoint.sh` that runs `alembic upgrade head` and then `exec "$@"`, failing the script on a migration error (design decision 1). Verify it is committed with its executable bit set (`git ls-files -s backend/docker-entrypoint.sh` shows mode `100755`)
- [ ] 1.2 Add `backend/tests/test_entrypoint.py` covering the entrypoint against a temporary SQLite `DATABASE_URL`: a fresh database gets the `users` and `nebius_api_keys` tables and the passed command runs; running it a second time against the same database succeeds and still runs the command; a `DATABASE_URL` that cannot be migrated exits non-zero and does not run the command. Verify with `cd backend && uv run pytest -q tests/test_entrypoint.py`
- [ ] 1.3 Point `backend/Dockerfile` at the entrypoint with `ENTRYPOINT ["/srv/docker-entrypoint.sh"]`, keeping the existing `CMD`, and `chmod +x` the script in the image. Verify with `docker build -t focus-funnel-backend-check backend/` and `docker run --rm --entrypoint sh focus-funnel-backend-check -c 'test -x /srv/docker-entrypoint.sh'`
- [ ] 1.4 Verify the backend suite is unaffected: `cd backend && uv run pytest -q` passes with no change to `backend/tests/conftest.py`

## 2. Proxy: a literal `%` in a path segment

- [ ] 2.1 Change `isSafeSegment` in `frontend/app/api/[...path]/route.ts` to check the segment as Next.js passes it and to add the decoded form only when decoding succeeds (design decision 2), with no `eslint-disable`, `any`, or empty `catch`
- [ ] 2.2 Add a proxy test that `ctx("thoughts", "100%")` returns 200 and reaches the backend as `/api/thoughts/100%25`. Verify it fails before the change and passes after
- [ ] 2.3 Move the `malformed encoding` case out of the rejection table into a test asserting `ctx("%E0%A4%A")` is forwarded as `/api/%25E0%25A4%25A`, and verify every remaining traversal case in the rejection table still returns 404 with no backend call

## 3. Proxy: backend redirects

- [ ] 3.1 Treat an upstream status in `300..399` as a failed backend call in `forward`: cancel the upstream body, log method, path, and status on the server, and return 502 `backend_unreachable` (design decision 3)
- [ ] 3.2 Add a proxy test where the backend answers `302` with a `Location` header, asserting the response is 502 with `{"error":{"code":"backend_unreachable", ...}}`, that no `location` header reaches the client, and that the logged arguments contain neither the access token nor a `Location` value

## 4. Proxy: the origin check

- [ ] 4.1 Add a comment on the `target.origin !== base.origin` guard in `backendTarget` recording that it is unreachable through the handler's inputs and kept as defense in depth over the `encodeURIComponent` path construction (design decision 4), adding no test and no code change

## 5. Gates

- [ ] 5.1 Verify no suppressions were added: `grep -rn "eslint-disable\|@ts-ignore\|@ts-expect-error\|@ts-nocheck" --include='*.ts' --include='*.tsx' --exclude-dir=node_modules --exclude-dir=.next .` returns nothing, and the diff adds no `any`, no `.skip`/`.only`, and no empty `catch`
- [ ] 5.2 Verify the frontend gates pass: `cd frontend && npm run build`, `npx tsc --noEmit`, `npm run lint -- --max-warnings 0`, and `npm test`
- [ ] 5.3 Verify the backend gate passes: `cd backend && uv run pytest -q`
- [ ] 5.4 Record the checks that need the compose stack and cannot run in this worktree (a fresh `docker compose up` creating the schema, and the full login-to-settings flow against it), with the exact commands for the session that has `.env`
