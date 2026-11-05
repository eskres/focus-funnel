## Context

See `proposal.md` for why. `auth-modes` and `model-providers` have landed, so this is what a new install has today:

- `backend/app/config.py`: `Settings` reads everything from the environment. `AUTH_MODE` is required and checked with its settings at startup (`oidc` needs `OIDC_ISSUER` and `OIDC_CLIENT_ID`; `firebase` needs `FIREBASE_PROJECT_ID`; demo refuses any `OIDC_*` or `FIREBASE_*` value and an explicit `ALLOW_CUSTOM_PROVIDER=true`). `AUTH_ALLOWED_EMAILS` is the allow-list. `KEY_ENCRYPTION_KEY` must decode to 32 bytes. `EMBEDDING_PROVIDER` must be a preset, never `custom`.
- The frontend server checks the same login settings itself (`lib/auth-mode.ts`, `instrumentation-node.ts` exits on a bad value) and holds the ones the backend never sees: `SESSION_SECRET`, `APP_BASE_URL`, `OIDC_CLIENT_SECRET`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`. So the login settings cannot change without restarting both servers.
- `main.py` lifespan: loads the settings, checks that the embedding provider is a preset, loads `chat.yaml`, and refuses to start without pgvector (`check_vector_extension`, which reads `pg_extension`). Migrations run in `docker-entrypoint.sh` before uvicorn, and migration `5e8b2c0d4a17` is what runs `CREATE EXTENSION IF NOT EXISTS vector`, so an unmigrated database has no `vector` row in `pg_extension` yet. `background-turns` makes the backend one process.
- Provider keys are per user (`provider_keys`, AES-GCM bound to the user id and provider id). `GET /api/providers` reports `key_saved` from the row without decrypting; `load_api_key` treats a row that does not decrypt (for example after `KEY_ENCRYPTION_KEY` changed) as no key. A preset with `key_required: false` works for every user with no row at all (`load_api_key` returns a placeholder). `resolve_provider` returns `provider_not_found` for a preset no longer in the file and raises 422 for `custom` when `ALLOW_CUSTOM_PROVIDER=false`. `PROVIDERS_CONFIG_PATH` replaces `providers.yaml`. A preset's `key_url` must be a non-empty string.
- `components/model-settings.tsx` offers a provider's models only when `usable()` holds: `key_saved || (!key_required && key_saved_at)`. A keyless preset with no row (and every keyless preset in demo mode, whose status never sets `key_saved_at`) is therefore not offered, although the backend would use it.
- The loadout is per user (`chat_models`, one `is_default`). `PUT /api/settings/models` checks every model against the provider's list for that user's key; `POST /api/settings/models/test` is the Test. The README states that the server configuration never chooses a model for a user.
- Search embeds with the user's own key for `EMBEDDING_PROVIDER` (Nebius by default), so a user who saved only an OpenRouter key can chat but cannot file or search.
- Frontend: `ProvidersSettings` dispatches `PROVIDER_KEYS_CHANGED` after a save; `ModelSettingsSection` listens for it. The API proxy (`app/api/[...path]/route.ts`) needs a login and forwards only `accept`, `accept-language`, and `content-type`. `proxy.ts` sends a logged-out visitor of any page but `/` (and `/login` in firebase mode) to log in with `returnTo`. Session cookies are always `Secure` (`lib/session.ts`), so a browser logs in only over `localhost` or HTTPS, as do passkeys.
- `backend/app/auth.py`: `OidcDiscovery` has only `fetch_jwks()`, which reads the discovery document internally with `httpx`; provider calls use `httpx2`. `FastAPI` answers a missing required `Header(...)` with 422 `validation_error` (`_handle_validation_error`) before any dependency runs.
- `app/layout.tsx` loads Geist and Geist Mono through `next/font/google`. The frontend Dockerfile builds a standalone server and sets no telemetry variable.
- `docker-compose.yml` builds `backend` and `frontend` with no image names; `backend` waits for `postgres` to be healthy (`depends_on: service_healthy`). Compose fills `${DATABASE_URL}`, `${POSTGRES_PASSWORD}`, `${BACKEND_URL}` from the project `.env` (or the shell), with `focus_funnel` defaults, so `docker compose up` works with no `.env`. `.env.example` already sets `POSTGRES_PASSWORD=focus_funnel` and a matching `DATABASE_URL`. Overlays exist for dev ports, demo, and Pocket ID (`ghcr.io/pocket-id/pocket-id:v2.16.0`); only the Pocket ID overlay sets `OIDC_INTERNAL_URL`, and it requires `POCKET_ID_ENCRYPTION_KEY` (`${...:?}`), so any compose command with it aborts when that is unset.
- `docs/login.md`'s Pocket ID steps tell the operator to copy `.env.example`, generate secrets with `openssl`, and open `http://localhost:1411/setup` (Pocket ID's own setup page).
- `backend/tests/conftest.py` defaults to `AUTH_MODE=oidc`, so every test that starts the app would open setup.
- `mcp-connectors` (planned, below this change in the stack): `MCP_ENABLED`, `MCP_USER_CONNECTORS`, `MCP_CONNECTORS_PATH`, and a `connectors.yaml` loader that refuses startup when an operator connector's `auth.env` variable is unset. Connector tokens live only in the environment.
- Operator commands run as modules in the backend image: `python -m app.reembed`.

## Goals / Non-Goals

**Goals:**

- The wizard writes nothing the settings screens cannot write, except one row that records that setup finished.
- One place for each option: the environment for anything instance-wide, the user's own settings for keys and models.
- The status endpoint and the `doctor` command share one set of checks and messages.
- An offline check anyone can run on one machine, that fails if the app needs the internet at run time.

**Non-Goals:**

- Writing `.env` or any login setting from the browser.
- Shared, instance-wide provider keys or a server-chosen model for users.
- Reopening setup once finished. The settings page does everything the wizard does.
- An admin role. Whoever finishes setup gets no rights other users lack.
- Building images inside the air gap. Images are built online and moved as files.
- Running a model server for the user outside the offline overlay.

## Decisions

### 1. Login settings stay in the environment; the wizard shows and checks them

Both servers validate `AUTH_MODE` and its settings before they serve anything, and the frontend holds secrets the backend never sees. A wizard that wrote them would need a running app to configure the thing that lets the app run, a restart of both processes after each change, and a second source of truth that both servers read. So step 1 of the wizard is read-only: it shows the mode, the non-secret values (issuer, client id, internal URL, project id), the allow-list entries, the names of every variable involved, and a link to `docs/login.md`. Choosing the mode happens before the first start, in `.env`, with help from the setup script (decision 10).

*Alternatives:* store login settings in the database and read them at each request (rejected: both servers would need the database before login works, and a bad value could lock the operator out with no file to fix); write `.env` from the backend container (rejected: the container does not own the file, and the frontend still needs a restart).

### 2. Keys and models stay per user; the wizard sets the operator's own

A provider key belongs to one user and is encrypted with that user's id; the loadout is per user, and the README says the server configuration never chooses a model for a user. The wizard's provider and model steps embed `ProvidersSettings` and `ModelSettingsSection` unchanged, so they call `PUT /api/providers/{id}/key`, `GET /api/providers/{id}/models`, `PUT /api/settings/models`, and `POST /api/settings/models/test` as the settings page does. What the operator saves there is their own key and loadout. Other users still set theirs in Settings, guided by the existing alerts.

The provider step adds one line above the component: which provider search uses (`EMBEDDING_PROVIDER`, by label) and that it needs a usable key, because that is the gotcha a first-time user hits when they only save a key for their chat provider.

One change to `ModelSettingsSection`: `usable()` becomes `key_saved || (!key_required && (!is_custom || Boolean(key_saved_at)))`. A keyless preset is then choosable with no row, matching `load_api_key` and the status's `search_key` rule, and in demo mode too. The custom provider still needs its saved row, because its base URL lives there. Without this change, "skip the wizard" (decision 3), the offline guide's "choose the Ollama model", and a status that shows `search_key` `ok` while the model step offers nothing would all fail.

### 3. Each option has one source, and the environment wins

| Option | Set by | The wizard |
|---|---|---|
| Auth mode and its settings | `AUTH_MODE`, `OIDC_*`, `FIREBASE_*`, `SESSION_SECRET`, `APP_BASE_URL` | shows, names the variables |
| Allow-list | `AUTH_ALLOWED_EMAILS` | shows, warns when unset |
| Database, key encryption key | `DATABASE_URL`, `KEY_ENCRYPTION_KEY` (setup script) | checks |
| Provider presets, custom provider | `PROVIDERS_CONFIG_PATH`, `ALLOW_CUSTOM_PROVIDER` | shows |
| Embedding model | `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | names the provider that needs a key |
| Connectors | `MCP_ENABLED`, `MCP_USER_CONNECTORS`, `MCP_CONNECTORS_PATH` | shows |
| The wizard itself | `SETUP_WIZARD` | — |
| The user's keys and loadout | the user, in Settings or the wizard | saves through the settings APIs |

The wizard writes no instance-wide option, so the environment always wins and nothing needs a precedence rule. A Docker or CI install skips the wizard with `SETUP_WIZARD=false`; with a providers file whose preset needs no key (decision 15), no user needs a key either. A CI script that needs a default model sets it with `PUT /api/settings/models` like any client.

`SETUP_WIZARD` is a boolean, default true. Demo mode follows the existing guard pattern: an explicit `SETUP_WIZARD=true` refuses startup naming it, otherwise demo forces it off. `.env.example` lists it empty (`SETUP_WIZARD=`), like `ALLOW_CUSTOM_PROVIDER=`, so a demo install built from `.env.example` still starts (`env_ignore_empty` reads empty as unset).

*Alternatives:* `DEFAULT_CHAT_MODEL` or instance-wide provider keys from the environment (rejected: they break the per-user key rule and the "never chooses a model" rule, and would need their own precedence against each user's choice).

### 4. When setup is open

One migration adds `setup_state`: `id` (integer primary key, always 1), `token_hash` (hex SHA-256, nullable), `token_created_at`, `completed_at` (nullable). The migration inserts the row and sets `completed_at` to now when any `users` row exists, so an install already in use never prints a token after the upgrade, even one whose users never chose a default model or use a keyless preset. Downgrade drops the table. Its `down_revision` is whatever head the stack has when it lands (`mcp-connectors`, `thought-dates`, and others add migrations below it), checked by `alembic heads`.

The row is created only by the migration. Production code never inserts it: a missing row (a recreated table, a partial restore, a manual delete) means setup is closed, and `open_setup()` prints one line saying so and naming the migration instead of a token. Tests get the row from the migration or a fixture.

Setup is open when all hold: `auth_mode` is `oidc` or `firebase`, `setup_wizard` is true, the row exists, and its `completed_at` is null. Demo mode never opens it: its visitors' keys live in their browser and no account outlives its session, so there is no operator account to set up.

While closed, every `/api/setup/...` route answers 404 `not_found`, as `mcp-connectors` does for a feature that is off, so a closed instance reveals nothing.

### 5. The setup token

At startup, after the pgvector check, the lifespan calls `open_setup()`. When setup is open it generates `secrets.token_urlsafe(24)` (192 bits, 32 characters), stores its SHA-256 hex digest and the time in the existing row, commits, and writes to stderr:

```
Focus Funnel setup is open.
Setup token: 3q9X...
Open http://localhost:3000/setup (the app's /setup, not Pocket ID's), log in, and enter this token.
A new token is printed each time the backend starts, until setup is finished.
```

The address is `APP_BASE_URL` + `/setup`, read from the process environment (the backend container gets it from `.env` through `env_file`; `Settings` does not hold it). When `APP_BASE_URL` is unset the line reads "Open /setup on the app (port 3000 by default, not Pocket ID's /setup)".

It goes to stderr with `print(..., flush=True)`, not through `logging`, so no log configuration can hide it, and it is never registered with `log_masking`. Each start replaces the hash, so a token in an old log stops working and a lost token is recovered by restarting the backend. A fast hash is enough because the token has 192 bits of entropy (the demo session hash uses the same reasoning); the check compares digests with `hmac.compare_digest`. No rate limit: guessing is not feasible. The token is not single use: it works for every request until the next start or until setup finishes.

While setup is open, a null `token_hash` (the migration's initial state, or `open_setup()` not yet run or failed) refuses every token with 403 `setup_token_invalid`; the check never passes `None` to `compare_digest`.

The token travels in the `X-Setup-Token` request header. The API proxy forwards `x-setup-token` only when the backend path starts with `setup/`, not through the global `FORWARDED_REQUEST_HEADERS`, so no other backend route (or a future middleware that logs headers there) ever receives it. No response, log line, or doctor output ever contains it.

*Alternatives:* print once and keep the hash across restarts (rejected: a lost log would need a reset command); a token in the URL (rejected: query strings land in access logs).

### 6. Log in first, then the token

Every setup route depends on `get_current_user` and then on `require_setup` (closed → 404, bad token → 403 `setup_token_invalid`). `require_setup` reads the header as `Header(default=None, alias="X-Setup-Token")`, so a request without it reaches the dependency instead of FastAPI's 422 `validation_error`; missing, empty, and wrong tokens all get the same 403 and message. The order of the answers a client sees: the proxy answers 401 for a logged-out browser before the backend runs; the backend answers 404 when closed before it looks at the token.

Login comes first because the provider and model steps save to a user, and login already works whenever the app runs: both servers refuse to start without valid login settings. When login itself fails (an issuer the containers cannot reach, a wrong client secret), the operator runs the doctor (decision 11), which needs no login. The token's job is to make sure that the person reading the instance's configuration and finishing setup can read the server's log. It grants nothing else: the setup routes write nothing but the finished flag.

### 7. `GET /api/setup/status`

```json
{
  "auth_mode": "oidc",
  "ready": false,
  "items": [
    {"id": "database", "state": "ok", "required": true,
     "message": "Postgres answers and has pgvector 0.8.1.",
     "settings": ["DATABASE_URL"]},
    {"id": "search_key", "state": "missing", "required": true,
     "message": "Search uses Nebius Token Factory. Save a key for it in the provider step.",
     "settings": ["EMBEDDING_PROVIDER", "EMBEDDING_MODEL"]}
  ]
}
```

`state` is `ok`, `missing`, `failed`, `warning`, or `info`; `ready` is true when every required item is `ok`.

| Item | Required | `ok` when | Otherwise |
|---|---|---|---|
| `database` | yes | `SELECT 1` and the pgvector version check pass | `failed`, with a fixed message per cause (could not connect, timed out, pgvector missing or too old) and the exception class name, never the driver's message |
| `encryption_key` | yes | always while the server runs; the message says to keep a copy | — |
| `login` | yes | always (the caller logged in); names the mode and its non-secret values and the variables: `oidc`: `AUTH_MODE`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_INTERNAL_URL`; `firebase`: `AUTH_MODE`, `FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN` | — |
| `allow_list` | no | set; names the entries and `AUTH_ALLOWED_EMAILS` | `warning`: anyone the provider lets in can use the instance (firebase: anyone who can sign in to the project); names `AUTH_ALLOWED_EMAILS` |
| `search_key` | yes | the caller's row for `EMBEDDING_PROVIDER` has a ciphertext that decrypts with the current `KEY_ENCRYPTION_KEY`, or the preset has `key_required: false` | `missing`, naming the provider; `failed` when a saved row does not decrypt: "the saved key cannot be read with the current KEY_ENCRYPTION_KEY; save it again" |
| `chat_model` | yes | the caller has a default model, its provider resolves (`provider_for_user` inside `try/except ApiError`), and it passes the same key test | `missing`: no default; the default's provider is no longer offered (removed from the providers file, or `custom` with `ALLOW_CUSTOM_PROVIDER=false`); or its key is missing. `failed` when its saved key does not decrypt |
| `custom_provider` | no | `info`: allowed or not | — |
| `connectors` | no | `info`: off, or on with the number of operator connectors and whether users may add their own | — |

The instance items (`database` through `allow_list`, `custom_provider`, `connectors`) are built by `app/setup/checks.py` from `Settings`, a database connection, and the loaded configuration files; the doctor uses the same functions (decision 11), except that its `login` item is `info` (mode and values), because the doctor has no logged-in caller; its live login check is step 6. The user items reuse `find_key_row`, `provider_for_user`, and `get_default_model`, and decrypt a saved row locally with `decrypt_secret` (the value is discarded at once and never registered or returned) so a key the server can no longer read is not reported as `ok`. Building the status makes no outbound call: whether a key still works is what the provider step's save and the model step's Test check.

A URL in any message (the database, the OIDC issuer, a provider, a connector) shows only scheme, host, port, and path: userinfo and the query string are dropped, so neither a `user:pass@` password nor a `?password=` or `?token=` value is printed.

"Setup complete" per auth mode:

| Mode | Required to finish |
|---|---|
| `oidc` | `database`, `encryption_key`, `login`, `search_key`, `chat_model`; `allow_list` is a warning only |
| `firebase` | the same; the `allow_list` warning is worded for a Firebase project |
| `demo` | setup never opens; the doctor reports the instance items |

### 8. Finishing setup engages the lock

`POST /api/setup/complete` (login and token) selects the `setup_state` row `with_for_update()` (as proposal confirm does), re-checks that setup is open (else 404), builds the status for the caller, and answers 409 `setup_incomplete` with the first missing required item's message when it is not `ready`. Otherwise it sets `completed_at`, clears `token_hash`, commits, prints "Setup is complete." to stderr, and answers 204. A second, concurrent request waits on the row lock and then finds setup closed (404). Nothing reopens setup; `SETUP_WIZARD=true` does not either.

New error codes: `setup_token_invalid` (403), `setup_incomplete` (409), added to `ErrorCode` and to the frontend's `ApiErrorCode`.

### 9. The wizard page

- `app/setup/page.tsx`: a logged-in page shaped like `app/settings/page.tsx` (same header). `proxy.ts` needs no change: `/setup` is not public, so a logged-out operator goes to login and returns.
- `components/setup/setup-wizard.tsx`: a token field first. The token is kept in `sessionStorage` (`focus-funnel:setup-token`) so a reload keeps it in that tab only; it is removed after Finish and on a 403 or 404. It is kept with the logged-in user's id (`GET /api/me`), so another user who logs in in the same tab is asked for the token instead of being sent the kept one, which is forgotten; without the id the token stays in memory only. A status read still on its way when Finish or a refusal lands is ignored. The embedded provider and model sections take a `returnTo` of `/setup`, so a login that runs out inside a step comes back to the wizard.
- A refused key in the provider step is `ProvidersSettings`' own error, shown as on the settings page; nothing is dispatched, so the status is not fetched again.
- `lib/setup.ts`: `getSetupStatus(token)` and `finishSetup(token)` through the existing `lib/api.ts` request helper, with the header.
- Four steps in the proposal's order, each listing its items with a state icon and message: **Login** (`login`, `allow_list`, the variable names, and "change these in `.env` and restart both servers"), **Provider** (the search provider line and `<ProvidersSettings />`), **Model** (`<ModelSettingsSection />` with its Test), **Server** (`database`, `encryption_key`, `custom_provider`, `connectors`). A Finish button is enabled when `ready`; after 204 the page says setup is complete and links to `/app`.
- The status is fetched again on `PROVIDER_KEYS_CHANGED` and on a new `MODEL_SETTINGS_CHANGED` event that `ModelSettingsSection` dispatches after a successful save.
- 404 shows "Setup is not open on this server" with links to Settings and the app. Nothing in the app links to `/setup`; the log line names it.

### 10. Bootstrap secrets: `scripts/init-env.sh`

A POSIX `sh` script at `scripts/init-env.sh`, using `openssl rand` as `.env.example` and `docs/login.md` already tell users to:

- It starts with `umask 077`, writes through a temporary file made with `mktemp` in the same directory as `.env` (never `/tmp`), removed by a `trap` on `EXIT INT TERM`, moves it into place, and ends with `chmod 600 .env`. A forced failure leaves no temporary copy of the secrets behind.
- No `.env`: copy `.env.example`, then fill `KEY_ENCRYPTION_KEY` (`openssl rand -base64 32`), `SESSION_SECRET` (`-hex 32`), and `POCKET_ID_ENCRYPTION_KEY` (`-base64 32`), and replace the example's `POSTGRES_PASSWORD=focus_funnel` with a new one (`-hex 16`) and `DATABASE_URL` with one that uses it. Exception: when `.data/postgres` exists and is not empty, the database was set up with compose's `focus_funnel` default (`docker compose up` works with no `.env`), so a new password would lock the backend out; the script keeps the example's Postgres values and prints a warning that says how to change the password inside Postgres first.
- Existing `.env`: fill only those of `KEY_ENCRYPTION_KEY`, `SESSION_SECRET`, and `POCKET_ID_ENCRYPTION_KEY` that are empty. Never touch `POSTGRES_PASSWORD` or `DATABASE_URL`, even when empty, because `.data/postgres` may already use them.
- `--auth-mode oidc|firebase|demo` sets `AUTH_MODE` only when it is empty; a set mode is left as it is and the script says so.
- Prints the names it filled (never the values), the settings the mode still needs (`OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`; `FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`), a warning to keep a copy of `KEY_ENCRYPTION_KEY` because saved provider keys cannot be read without it, a note when `MCP_ENABLED=true` that connector tokens go in `.env` under the names `connectors.yaml` gives and are not generated (decision 17), and the next steps: for `oidc` with Pocket ID, start `pocket-id` first and register the client (`docs/login.md`); then `docker compose up`, then the app's `/setup` with the token from `docker compose logs backend`.

*Alternatives:* a compose init service (rejected: compose reads `.env` for interpolation before any service runs, so the file must exist first); a Python script (rejected: the host may not have the right Python; `openssl` is already assumed by the docs).

`docs/login.md`'s Pocket ID steps 1–2 (copy `.env.example`, run `openssl`) become "run `scripts/init-env.sh --auth-mode oidc`", step 4 says that `http://localhost:1411/setup` is Pocket ID's own setup page and the app's wizard comes later, and steps 7–8 end with the app's `/setup` and the token from the backend log.

### 11. The `doctor` command

`backend/app/doctor.py`, run as `python -m app.doctor [--json]`. In compose, with the same `-f` files the install runs with, because `OIDC_INTERNAL_URL` is set only by the Pocket ID overlay and the offline providers file and `EMBEDDING_*` only by the offline overlay:

```sh
docker compose -f docker-compose.yml -f docker-compose.pocket-id.yml run --rm --entrypoint python backend -m app.doctor
# Postgres is the suspect: do not wait for it to be healthy
docker compose -f docker-compose.yml -f docker-compose.pocket-id.yml run --rm --no-deps --entrypoint python backend -m app.doctor
```

The docs recommend `COMPOSE_FILE=docker-compose.yml:docker-compose.pocket-id.yml` (or with the offline overlay) in `.env`, so every compose command, the doctor's included, uses the same files without `-f`. `--entrypoint python` skips the migration entrypoint, so the doctor runs when the backend cannot start, which is when it is needed. It never imports `app.main`, so no lifespan runs and no setup token is made.

Checks, in order, each bounded by 5 seconds (`asyncio.wait_for`):

1. **settings**: build `Settings()`. On a `ValidationError`, one `failed` line per error, built only from `err["loc"]` (the variable name, upper-cased) and `err["msg"]`, never from `str(exc)` or `err["input"]`, which hold the bad value (a wrong `KEY_ENCRYPTION_KEY` or `SESSION_SECRET`). An `AUTH_MODE` error says it must be `oidc`, `firebase`, or `demo`. The later checks that need settings are `skipped`. The database is still checked with `DATABASE_URL` read directly.
2. **config files**: `providers.yaml` (or `PROVIDERS_CONFIG_PATH`), `chat.yaml`, the embedding preset check, and `connectors.yaml` when `MCP_ENABLED`; each loader's own error message on failure (for `connectors.yaml`, the connector and the unset `auth.env` variable, never a value).
3. **instance items** from `app/setup/checks.py` (decision 7), with the same ids and messages; `login` is `info` here (decision 7). The database line shows the URL as decision 7 redacts it, with the password replaced by `***`. When `alembic_version` is missing or behind the head, the pgvector part reads `pg_available_extensions` instead of `pg_extension`: `vector` available but not created is a `warning` ("not migrated yet; the backend creates the extension when it starts"), not available is `failed`. A fresh install, or one whose migration failed, is then not reported as lacking pgvector.
4. **migrations**: `alembic_version` against the script head; missing ("not migrated yet") or behind is a `warning` ("the backend applies them when it starts").
5. **setup**: open, finished, off (`SETUP_WIZARD=false`), not used (demo), or, when the `setup_state` table or row is missing, a `warning` ("not migrated yet" or "setup record missing; setup is closed"). When open: "restart the backend to print a new token". The token is never printed; the doctor only has its hash.
6. **login provider**: `oidc` fetches the discovery document through a new `OidcDiscovery.fetch_document()` (honoring `OIDC_INTERNAL_URL`; `fetch_jwks()` is changed to call it) and checks that its `issuer` equals `OIDC_ISSUER`; a fetch that fails is `failed` and names the URL it fetched (redacted); `firebase` fetches Google's signing keys; demo is `skipped`. Tests inject an `httpx` transport here and an `httpx2` transport for steps 7 and 8.
7. **providers**: for each preset in the loaded file, `GET {base_url}models` with no key. Any HTTP answer is reachable. For a `key_required: false` preset, a model list also reports how many models it has and whether `EMBEDDING_MODEL` is among them. Unreachable is `failed` for the `EMBEDDING_PROVIDER` preset (search cannot work) and a `warning` for the others. Custom provider URLs are per user and not checked.
8. **connectors** (when `MCP_ENABLED`): each operator connector URL; any HTTP answer is reachable, otherwise a `warning`. The line names the connector and the URL's scheme, host, and port only, since a `connectors.yaml` URL may carry `user:pass@` or `?token=` despite `auth.env` being the intended place. No MCP session is opened, so the doctor does not depend on the MCP SDK.

Each line: `ok       database   Postgres answers and has pgvector 0.8.1.` Exit status 0 when nothing `failed`, 1 otherwise. `--json` prints `{"items": [...]}` with the status item shape plus `skipped`.

The frontend checks its own settings at start, so the doctor ends with an `info` line pointing at `docker compose logs frontend` for those.

### 12. Outbound calls, one by one

| Call | From | Offline install |
|---|---|---|
| Nebius, NVIDIA, OpenRouter | backend, when a user uses them | the offline providers file lists only the local server |
| Embeddings | backend | `EMBEDDING_PROVIDER` is the local preset |
| OIDC discovery, keys, token | backend and frontend server | an issuer inside the install (Pocket ID), reached through `OIDC_INTERNAL_URL` |
| Firebase keys and token refresh | backend and frontend server | cannot work offline; the guide says to use `oidc` |
| Next.js telemetry | `next build` (the CLI) | `NEXT_TELEMETRY_DISABLED=1` (decision 13) |
| Google Fonts | `next build` only | already self-hosted (decision 13) |
| Pocket ID analytics heartbeat (`POST https://analytics.pocket-id.org/heartbeat`, at start and daily) | `pocket-id` container | `ANALYTICS_DISABLED=true` in `docker-compose.pocket-id.yml` (confirmed for v2.16.0 by task 1.1) |
| Pocket ID release check (`GET https://api.github.com/repos/pocket-id/pocket-id/releases/latest`, when an admin opens a settings page) | `pocket-id` container | `VERSION_CHECK_DISABLED=true` in `docker-compose.pocket-id.yml` (found by task 1.1) |
| MCP connectors | backend, on Test or a tool call | only operator connectors on the compose network (decision 17) |
| Image pulls | `docker compose up` | `--no-build --pull never` (decision 14) |
| A preset's key and console links | the browser, only when clicked | the offline preset's `key_url` is the Ollama model library (`https://ollama.com/library`); nothing loads it, and its notice points at `docs/offline.md` for pulling models. The compose-internal `http://ollama:11434` is not used, because the browser cannot reach it |

*Task 1.1 result (2026-11-05, `ghcr.io/pocket-id/pocket-id:v2.16.0`, index digest `sha256:9366436f3fd21619ed7e5709fa0acac88130f73414ec8ee1caf768fc487111ea`):* the variable names come from that tag's `backend/internal/common/env_config.go` and the configuration docs. Pocket ID was started with the Pocket ID overlay on the compose project's own bridge, and `tcpdump -ni br-<id> 'not dst net <subnet> and not dst host 127.0.0.1'` ran during admin setup (`/setup`), adding a passkey, opening the admin settings pages, and one OIDC login: authorization code by passkey in the browser, then discovery, token, JWKS, and userinfo through `http://pocket-id:1411`, as the app does them. The sandbox resolves no outside names, so a DNS sinkhole on the same network answered every name with a TEST-NET address and logged the names. That way every name-based call became a packet the capture could see. Results:

- Both variables unset: packets to the sinkhole address on port 443, for `analytics.pocket-id.org` and `api.github.com`.
- `ANALYTICS_DISABLED=true` alone: packets for `api.github.com` only. This is the release check that `/api/version/latest` makes when the admin pages load.
- `ANALYTICS_DISABLED=true` and `VERSION_CHECK_DISABLED=true`: no packet to an outside address, and no name looked up.

The source has other outbound calls, and each one is off unless an operator sets something:

- The GeoLite2 download runs only with `MAXMIND_LICENSE_KEY` or a custom `GEOLITE_DB_URL`.
- Down migrations come from GitHub only with `ALLOW_DOWNGRADE=true`.
- Client logos are fetched from a URL only when an admin enters one.
- SCIM, back-channel logout, and federated JWKS calls happen only when they are configured.
- The OpenTelemetry exporters are off by default.

None of these needs a setting in the overlay.

### 13. Fonts and telemetry

`next/font/google` downloads Geist at build time and serves the files from `/_next/static/media` with the rest of the build; the page and its CSS name no Google host, and the browser never contacts Google. Since images are built online and moved as files (decision 14), the fonts are already self-hosted, and `layout.tsx` stays as it is. The offline check asserts it (decision 16).

`ENV NEXT_TELEMETRY_DISABLED=1` goes in the frontend Dockerfile's `build` and `run` stages: the build stage is where Next.js telemetry runs, and the run stage keeps it off for anyone who runs the CLI in the container.

*Alternative:* the `geist` npm package through `next/font/local`, so a build needs no font download (rejected for now: only matters for building inside the air gap, a non-goal; it adds a dependency).

### 14. Moving images with `docker save`

`docker-compose.yml` gets `image: focus-funnel-backend:${FOCUS_FUNNEL_TAG:-local}` and `image: focus-funnel-frontend:${FOCUS_FUNNEL_TAG:-local}` beside `build:`, so a build tags the images with names that survive `docker save`. `scripts/bundle-images.sh [-f overlay ...]` runs `docker compose <files> build`, `pull --ignore-buildable`, lists `config --images`, and writes `docker save <images> | gzip > focus-funnel-images-<tag>.tar.gz` with its SHA-256. By default it uses the base file, `docker-compose.offline.yml`, and `docker-compose.pocket-id.yml`. It runs every compose command with `--env-file` pointing at a generated placeholder file (`POCKET_ID_ENCRYPTION_KEY=placeholder-for-bundling`), so the Pocket ID overlay's `${...:?}` does not abort on a build machine with no `.env`; the placeholder never reaches an image. On the offline host: `gunzip -c <archive> | docker load`, then `docker compose <files> up --no-build --pull never`.

### 15. The offline install overlay

`docker-compose.offline.yml`:

- `ollama`: `ollama/ollama` at the version task 1.2 pins, data in `.data/ollama`, no published port.
- `backend`: mounts `deploy/offline/providers.yaml` and sets `PROVIDERS_CONFIG_PATH` to it, `EMBEDDING_PROVIDER=ollama`, `EMBEDDING_MODEL=${OFFLINE_EMBEDDING_MODEL:-<task 1.2>}`, and `EMBEDDING_DIMENSIONS=native` (the index has no fixed dimension, and task 1.2 checks whether Ollama honors `dimensions`).

`deploy/offline/providers.yaml` holds one preset, `ollama`: `base_url: http://ollama:11434/v1/`, `key_required: false`, `key_url: https://ollama.com/library` (decision 12), a notice that prompts stay on the operator's server and that models are pulled as `docs/offline.md` says, all `model_list` capabilities false, and the `stream_usage` task 1.2 measures. It is a preset rather than the custom provider because `EMBEDDING_PROVIDER` cannot be `custom`, and because a preset needs no per-user setup. The overlay does not mark the network internal: the browser must reach port 3000, and an air-gapped host has nothing outside to reach anyway. The internal network is the offline check's job.

Models are pulled on an online machine into the same `.data/ollama` (`docker compose ... up -d ollama`, then `docker compose ... exec ollama ollama pull <model>`; decision 21) and the directory is copied with the image archive.

The browser must reach the app over `localhost` or HTTPS (Context: `Secure` cookies and passkeys). On an air-gapped host the guide uses a browser on that host, or HTTPS on the LAN with Caddy's `tls internal` as in `docs/login.md`'s "HTTPS on your network"; a browser on another machine reaching the host's IP over plain HTTP cannot log in.

*Task 1.2 result (2026-11-05):* the image is `ollama/ollama:0.40.14` (digest `sha256:ebaef4f4c5d93660e1f25f8ad085a112f51ccfb0e8458073e71793959dba91c9`). The proposed models are `qwen3:1.7b` for chat (the library lists it with tools and thinking, 1.4 GB) and `nomic-embed-text:v1.5` for embeddings (768 dimensions, 274 MB). This sandbox's proxy refuses `registry.ollama.ai`, `ollama.com`, and `huggingface.co`, so neither model could be pulled. The calls ran through the backend's `openai` client against that image, using two local stand-in models: a random-weight llama GGUF for chat, and a random-weight 768-dimension BERT GGUF for embeddings. Those calls measured the server's behavior, but not the chosen models'. Results:

- `stream_usage`: `final_chunk`. With `stream_options.include_usage`, the usage arrives once, on a last chunk with empty `choices` after the finish chunk, and no other chunk carries usage.
- `dimensions` is honored. Without it, embeddings are 768 long; with `dimensions: 256`, they are 256 long (truncated and renormalized). A value above the native length, or outside a model's trained Matryoshka set, is a 400 error. `EMBEDDING_DIMENSIONS=native` sends no `dimensions`, so the overlay keeps it.
- `/v1/models` answers `{"object":"list","data":null}` while no model is pulled. The backend's model listing iterates the page, so it reads that as an empty list.
- Ollama 0.40.14 has no `tool_choice` field and ignores it, so a forced tool call depends on the model choosing the tool.

Still to check on a machine that reaches the Ollama registry (task 1.2 stays open until then): that `qwen3:1.7b` returns a streamed tool call for a forced function, and that `nomic-embed-text:v1.5` returns 768-dimension vectors.

### 16. The offline check

`docker-compose.offline-check.yml`, `deploy/offline/check/` (`providers.yaml`, `stub_provider.py`, `smoke.py`), and `scripts/offline-check.sh`:

- The overlay marks `networks: default: {internal: true}`, gives `postgres` a `tmpfs` instead of `.data` (as the demo overlay does), resets `env_file` for `backend` and `frontend` and sets demo mode with fixed test-only secrets, sets `DATABASE_URL`, `POSTGRES_PASSWORD`, and `BACKEND_URL` explicitly, removes the frontend's published port (an internal network cannot publish), and points the backend at the check's providers file (one `stub` preset, `key_required: false`) with `EMBEDDING_PROVIDER=stub`. Resetting `env_file` alone does not stop compose from interpolating `${...}` from the project `.env`, so `scripts/offline-check.sh` passes `--env-file deploy/offline/check/check.env` (fixed, test-only values) to every compose call: an operator's `.env` cannot leak in or break demo mode.
- `stub-provider` and `smoke` run from the backend image with the check directory mounted and an `entrypoint` override, so the check needs no extra image. `stub_provider.py` uses only the standard library: `GET /v1/models`; `POST /v1/embeddings` with deterministic vectors from a hash of the text; `POST /v1/chat/completions` streaming either a tool call for the forced function (arguments valid for the schemas in `prompt.tools_for`) or, once a tool result is present, a short text answer, with a final usage chunk; and `GET /_log` with the paths it served.
- `scripts/offline-check.sh [-f extra.yml ...]` builds the images (online), then runs `up -d --no-build --pull never` with project name `ff-offline-check`, then `run --rm smoke`, then `down -v --remove-orphans` in a trap, and exits with the smoke test's status. Extra `-f` files are appended to the compose files; `deploy/offline/check/not-internal.yml` (`networks: default: {internal: false}`) is the fixture that proves step 1 fails on an ordinary network.
- `smoke.py` steps, each printed by name: (1) `https://example.com` and `http://1.1.1.1` must fail to connect, else "the network is not internal"; (2) `GET /` on the frontend starts a demo session (the cookie is copied by hand, because the client's cookie jar does not send a `Secure` cookie over plain HTTP); (3) `/app` and every stylesheet it links reference only relative or same-origin URLs, and no `fonts.googleapis.com` or `fonts.gstatic.com`; (4) `PUT /api/settings/models` with the stub model as default; (5) `/push` gives a `proposal` event, then confirm answers 200; (6) `/pull` gives a source with the confirmed title; (7) the stub's `/_log` shows the model list, chat, and embeddings calls.

Demo mode is used because it needs no login, and it runs every runtime path that could reach out (page serving, the proxy, provider and embedding calls) except login, which the offline guide's manual run covers with Pocket ID.

### 17. Connectors (`mcp-connectors`)

The status's `connectors` item and the doctor read the settings and the `connectors.yaml` loader that `mcp-connectors` adds, and nothing else from that change. Connector tokens stay in the environment variables that `connectors.yaml` names, set in `.env`; the setup script does not generate them (they come from the connected service), and says so when `MCP_ENABLED=true`. `docs/setup.md` and `docs/offline.md` say the same. The loader already refuses startup when one is unset, so the doctor reports that as a config-file failure naming the connector and the variable. Connector URLs are printed redacted (decision 11 step 8). The offline guide says that operator connectors work offline only as sidecars on the compose network (the `docker-compose.mcp.yml` pattern) and that user connectors to outside URLs cannot.

### 18. Status details left open by decision 7

Decision 7 fixes the items and their rules; these choices fill in what it leaves open, each the simplest that fits the spec.

- **Order and the 409 message.** The items come in the order of decision 7's table (`database`, `encryption_key`, `login`, `allow_list`, `search_key`, `chat_model`, `custom_provider`, `connectors`). "The first missing item" is the first required item that is not `ok` in that order, and `setup_incomplete` carries that item's own message, so a missing default model answers "Choose a default model in the model step."
- **Values in messages.** An item carries no fields beyond id, state, required, message, and settings, so the non-secret values the wizard shows are in the messages: the `login` message names the issuer, client id, and internal URL (or the Firebase project), and the `allow_list` message lists its entries or says "none set". The `custom_provider` item also lists the preset labels and names `PROVIDERS_CONFIG_PATH`, since decision 3 says the wizard shows the presets.
- **A keyless preset with a row that does not decrypt** is `ok` for `search_key` and `chat_model`, as `load_api_key` then sends the placeholder key and the provider works. `failed` is only for a preset that needs a key.
- **SQLite** (tests only) gets `database` `ok` "The database answers." with no pgvector check, as the startup check does.
- **Connectors before `mcp-connectors` lands.** The item reads `mcp_enabled` and `mcp_user_connectors` with `getattr` and imports the `connectors.yaml` loader only when connectors are on, so on a branch without that change it reports "Connectors are off." and still names `MCP_ENABLED`, `MCP_USER_CONNECTORS`, and `MCP_CONNECTORS_PATH`.
- **Redaction is cautious.** `redact_url` takes the userinfo to end at the last `@` before the query (or the last `@` anywhere when only the query has one), so an unencoded `/` or `?` in a password cannot leak part of it as the host; a string with no `://` is shown as "(not a URL)".

*Alternatives:* extra structured fields on the items for the login values (rejected: the spec's item shape has none, and the wizard can render messages); a `failed` search key for any undecryptable row (rejected: it would block finishing on an install whose search works).

### 19. How the wizard page tells "closed" from "needs the token"

Decision 9 puts the token field first, and the spec says a logged-in user who opens `/setup` after setup has finished is told it is not open. The backend answers 404 before it reads the token (decision 6), so the page asks once without one. On load, with no token kept in the tab, it calls `GET /api/setup/status` without `X-Setup-Token`: 404 shows "Setup is not open on this server." with links to Settings and the app, and 403 shows the token form with no error (the refusal is shown only for a token the operator entered or the tab kept). With a kept token it calls with that token, and a 403 or 404 forgets it as decision 9 says. A 401 sends the user to log in with `returnTo=/setup`. Other failures show their message: on the token form while the steps are not yet shown, or above the steps when a refresh fails, which keep the last status.

The steps render the status as it comes: each item's name, state, message, and `settings`. The login step adds the mode and the union of the `login` and `allow_list` variable names; the issuer, client id, and allow-list entries come from the item messages (decision 18). The provider step shows the `search_key` item above `ProvidersSettings`, the model step the `chat_model` item above `ModelSettingsSection`, and the server step the rest. A 409 on Finish shows the server's message and reads the status again. `ProvidersSettings` and `ModelSettingsSection` stay unchanged apart from decision 2 and the new event, so an expired login inside one of them still returns to `/settings`, not `/setup`.

*Alternatives:* show the token form first and learn that setup is closed only after a token is entered (rejected: a user without a token, which is everyone after setup, could never see the closed message); a separate unauthenticated "is setup open" route (rejected: it would tell anyone whether an instance is unconfigured, which the 404 rule avoids).

### 20. Doctor details left open by decision 11

Decision 11 fixes the steps and their rules; these fill in what it leaves open, each the simplest that fits the spec.

- **Ids.** The doctor's own lines use the ids `settings` (one line per settings error), `providers_file`, `chat_file`, `connectors_file` (only when connectors are on), `migrations`, `setup`, `login_provider`, `provider:<preset id>`, `connector:<name>`, and `frontend`. The instance items keep their status ids. Lines come in step order, with `migrations` after the instance items. An item's `required` is true for what the server cannot work without (settings, the files, the database, migrations, the login provider, and the embedding preset).
- **One database probe.** One connection, bounded by 5 seconds as a whole, reads `SELECT 1`, the table names, `alembic_version`, the installed and available `vector` versions, and only `setup_state.completed_at`, never the token hash. The `database`, `migrations`, and `setup` lines are built from that. When it fails, `migrations` and a setup that would need the row are `skipped`. The engine uses `NullPool`, asyncpg gets the same connect timeout, and `dispose()` is itself bounded, so a server that accepts and never replies cannot hold the doctor past the limit.
- **States.** Setup open is `info` ("restart the backend to print a new setup token"), finished is `ok`, off and not used are `info`. A database at a revision this backend's scripts do not know is `failed` (it was migrated by a newer version, and the entrypoint's `alembic upgrade head` would fail). A keyless embedding preset that answers without `EMBEDDING_MODEL` in its list is a `warning`, since search fails until the model is added; for other keyless presets the model count and the `EMBEDDING_MODEL` note are information on an `ok` line. A failed HTTP status from the login provider is named by its code (`HTTP 404`); every other error by its class.
- **Settings error names.** An error on a field names that field upper-cased. A rule across fields (`loc` empty) names the first `NAME_LIKE_THIS` in its own message, which is how `AUTH_MODE` and the per-mode variables are named in the line and in its `settings`.
- **Connectors before `mcp-connectors` lands.** As decision 18: `MCP_ENABLED` is read with `getattr`, and the loader is `app.setup.checks.load_connector_config`. Its `ConnectorConfigError` (a `ValueError`) message is shown as is; any other error by class only.

*Alternatives:* one connection per line (rejected: three connects for one question, each needing its own timeout); `warning` for an open setup (rejected: an open setup is the expected state of a new install, not a problem to look into).

### 21. Offline files: details left open by decisions 14 to 16

Decisions 14 to 16 fix the files and what they do; these fill in what they leave open, each the simplest that fits the spec.

- **Only the local server is offered.** The offline overlay sets `ALLOW_CUSTOM_PROVIDER: ${ALLOW_CUSTOM_PROVIDER:-false}`, so the provider list offers only `ollama`, as the spec's "A keyless local provider" scenario says. Without it, the default (`true`) also lists `custom`. An operator who sets `ALLOW_CUSTOM_PROVIDER=true` in `.env` still gets it back, since the environment decides (decision 3).
- **Pulling models.** The Ollama image's entrypoint is the `ollama` binary, and `ollama pull` talks to a running server, so `run --rm ollama ollama pull` does not work. The guide starts the service and pulls with `exec`.
- **`bundle-images.sh -f`** replaces the two default overlays; `docker-compose.yml` is always first. It is a bash script (`pipefail`, so a failed `docker save` is not hidden by `gzip`) and writes the archive under a temporary name, moved into place only when complete.
- **`offline-check.sh`** builds by default, as decision 16 says, so a changed `layout.tsx` is checked. `--no-build` (or `OFFLINE_CHECK_NO_BUILD=1`) uses the images already built; the services themselves always start with `up --no-build --pull never`. Extra `-f` files are added to every call, including the build.
- **The check's overlay writes its settings out.** `postgres`, `backend`, and `frontend` get literal test-only values (demo mode, the database URL and password, a zero `KEY_ENCRYPTION_KEY`, a fixed `SESSION_SECRET`), not `${...}` references, so neither the project `.env` nor the operator's shell can change them. `check.env` holds the same values for the base file's own `${...}` references. `smoke` is behind a `smoke` profile, so `up` does not start it, and `down --volumes --remove-orphans` with that profile removes everything the check made.
- **Smoke test details.** Before step 1 it waits up to 180 seconds for the backend's `/health`, the frontend's `/favicon.ico` (outside the demo proxy, so it starts no session), and the stand-in. Step 1 opens raw TCP connections, because a TLS error after a connection (for example from an intercepting proxy) still means the network is not internal. Step 3 checks the `src`, `href`, and `srcset` of every tag that loads something, and every `url()` and `@import` in inline styles and linked stylesheets, then fetches each linked script, stylesheet, and font from the app. The stand-in's embeddings count hashed words, so `/pull` finds the thought by meaning as well as by words.

*Alternatives:* a separate image for the stand-in and the smoke test (rejected: decision 16 runs them from the backend image, which already has Python); an offline check that never builds (rejected: a font or script reference added in a page would not be checked until someone rebuilt the images).

## Risks / Trade-offs

- [The token sits in the backend log, and log shippers keep it] → it is invalid after the next restart or once setup finishes, and it grants only the configuration report and the finished flag, never data or keys.
- [An operator never finishes, so setup stays open] → the token rotates at each start, every setup route also needs a login, and the routes write nothing but the finished flag.
- [Two backend processes would print two tokens and only the last write works] → `background-turns` already requires one process; the docs say so.
- [The wizard's checks pass, but a key stops working later] → the status reports saved state without calling out; the provider step's save and the model step's Test are the live checks, and the doctor checks reachability.
- [A demo-mode check misses an outbound call only `oidc` makes] → the manual run in the offline guide uses `oidc` with Pocket ID on an air-gapped host.
- [Next.js or a dependency adds a runtime call later] → the offline check fails on it, as long as it is run before a release.
- [The setup script differs between `sed` implementations] → it uses only POSIX `sed` with a temporary file in the `.env` directory, tested on the BusyBox and GNU versions in task 5.1.
- [`.env` holds every bootstrap secret] → the script writes it with `umask 077` and `chmod 600`, and leaves no temporary copy behind.
- [The `setup_state` row is lost on an install in use] → a missing row means closed (decision 4); production code never recreates it, so setup cannot reopen by accident.
- [The doctor is run without the overlays the install uses] → its issuer and provider lines would check the wrong addresses; the docs give the full command and recommend `COMPOSE_FILE` in `.env`.

## Migration Plan

One Alembic migration adds `setup_state` and marks an install with any user as finished; downgrade drops the table. Existing installs see no token and no change. The compose image names (decision 14) change only the tag of locally built images. Rolling back the code with the table present is safe: nothing else reads it.

## Open Questions

- Resolved by task 1.1: the Pocket ID variables are `ANALYTICS_DISABLED` and `VERSION_CHECK_DISABLED` (decision 12). Partly resolved by task 1.2: the image is `ollama/ollama:0.40.14` and `stream_usage` is `final_chunk` (decision 15). The proposed models `qwen3:1.7b` and `nomic-embed-text:v1.5` still need a run that pulls them. The design does not depend on which models are chosen.
