# Focus Funnel

Focus Funnel is a chat app for brain dumps. You write to-dos, ideas, and half-formed thoughts. One chat model talks them through with you and proposes short notes to file.

You bring your own model provider. Each user saves their own API key for Nebius, NVIDIA, OpenRouter, or any OpenAI-compatible server, such as Ollama. The keys are stored encrypted.

## What works now

- **Chat:** one model sees the whole conversation and can use two tools. It searches your filed thoughts, or it proposes a thought to file. Answers stream as they are written.
- **Commands:**

  | Command | What it does |
  |---|---|
  | `/push text` | Proposes a thought to file |
  | `/pull text` | Searches your filed thoughts |
  | `/explore text` | Discusses a thought, with no tool forced |
  | `/delete` | Deletes the open conversation, after you confirm |

- **Conversations:** each conversation is stored. The sidebar lists them newest first, and you can rename, archive, restore, or delete each one.
- **Models:** in Settings you choose up to five models. One of them is the default. Each model has a reasoning effort, and you set one temperature for all of them. The message box has a dropdown to switch model inside a conversation.
- **Filing:** a proposal shows as a card you can edit. Confirm saves it as a thought, with the text you wrote as its raw text, and the card links to it. A message with several things to keep shows one card per part, and "Merge into one" joins them. Each thought has a category: one of six fixed kinds, or one you add in **Settings**.
- **Search:** the search tool finds your filed thoughts by meaning and by words at once, in Postgres with pgvector. The thoughts an answer used show under it as sources, which you can sort newest first and filter by tag. [docs/search.md](docs/search.md) covers the embedding model, tuning, and rebuilding search indexes.
- **Thoughts:** a source or a saved card opens the thought in a side sheet over the chat. The address names the open thought, so you can copy it, and Back closes the sheet.
- **Export:** In **Settings**, download all your thoughts as one JSON or Markdown file.
- **Connectors (off by default):** the chat can use tools from MCP servers, such as a Google Calendar server you run yourself. Reads run at once; anything that changes something shows a card and waits for your approval, unless you set that tool to always allow. [docs/connectors.md](docs/connectors.md) covers the switches, the risks, and the Google Calendar example with `docker-compose.mcp.yml`.

## Stack

| Part | Technology |
|---|---|
| Frontend | Next.js (App Router), shadcn/ui with Base UI, Tailwind |
| Backend | FastAPI (async), SQLAlchemy, Alembic |
| Database | Postgres with pgvector for thought search (SQLite in tests) |
| Login | Any OpenID Connect provider (such as Pocket ID), Firebase, or an anonymous demo mode |
| Models | Any OpenAI-compatible API, through the `openai` SDK |

The browser talks only to the Next.js server. The Next.js server runs the login, keeps the session in an encrypted cookie, and forwards `/api/...` calls to FastAPI with the user's ID token. The backend has no public port.

## Run it with Docker

You need Docker and `openssl`. Login is set up with `AUTH_MODE` in `.env`: an OpenID Connect provider, a Firebase project, or an anonymous demo. [docs/login.md](docs/login.md) explains each one. The quickest start is Pocket ID, which runs next to the app. [docs/setup.md](docs/setup.md) covers each step in detail.

1. Generate `.env` with new secrets. Keep a copy of the `KEY_ENCRYPTION_KEY` it sets:

   ```sh
   scripts/init-env.sh --auth-mode oidc
   ```

2. Start Pocket ID on its own and register the app with it, as steps 4 to 6 of [Pocket ID in docs/login.md](docs/login.md#pocket-id) describe. Then fill `OIDC_ISSUER`, `OIDC_CLIENT_ID`, and `OIDC_CLIENT_SECRET` in `.env`:

   ```sh
   docker compose -f docker-compose.yml -f docker-compose.pocket-id.yml up -d pocket-id
   ```

3. Start everything, and find the setup token in the backend's log:

   ```sh
   docker compose -f docker-compose.yml -f docker-compose.pocket-id.yml up -d --build
   docker compose -f docker-compose.yml -f docker-compose.pocket-id.yml logs backend | grep 'Setup token'
   ```

4. Open the app's http://localhost:3000/setup, log in with your passkey, and enter the token. The wizard checks the login settings and the database, saves your API key, and sets your default chat model. Click **Finish** when every required item is OK.

Other users save their own key and choose their models in **Settings**.

Without the Pocket ID overlay, for example with another OpenID Connect provider or Firebase, run the script with that mode, fill in its settings in `.env`, and start everything with the command below. Then find the token with `docker compose logs backend` and open `/setup` as in steps 3 and 4.

```sh
docker compose up --build
```

To use the same compose files in every command without `-f`, set `COMPOSE_FILE` in `.env`. `SETUP_WIZARD=false` skips the wizard, and the doctor (`python -m app.doctor`) checks an install from the command line. [docs/setup.md](docs/setup.md) covers all three.

The backend applies database migrations each time it starts. Postgres keeps its data in `.data/`.

To install on a host with no internet, with a local Ollama server for chat and search, follow [docs/offline.md](docs/offline.md).

To expose the backend on port 8000 and Postgres on port 55432 for debugging, run:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

## Develop

### Backend

The backend needs Python 3.14 and [uv](https://docs.astral.sh/uv/).

```sh
cd backend
uv sync
uv run pytest
```

The tests use SQLite by default. To run them against Postgres, set `TEST_DATABASE_URL`, for example to a test database in the compose Postgres from `docker-compose.dev.yml`. Use a database of its own, never the app's: the tests drop every table they create. Create it once:

```sh
docker compose exec postgres createdb -U focus_funnel focus_funnel_test
TEST_DATABASE_URL=postgresql+asyncpg://focus_funnel:focus_funnel@localhost:55432/focus_funnel_test uv run pytest
```

Thought storage and search need Postgres with pgvector, so their tests are marked `postgres` and left out of the runs above. Run them on their own, against a Postgres that has the `vector` extension, such as the compose one:

```sh
TEST_DATABASE_URL=postgresql+asyncpg://focus_funnel:focus_funnel@localhost:55432/focus_funnel_test uv run pytest -m postgres
```

Without `TEST_DATABASE_URL` they fail instead of being skipped.

To create a migration after you change a model:

```sh
DATABASE_URL=sqlite+aiosqlite:///./dev.sqlite3 uv run alembic upgrade head
DATABASE_URL=sqlite+aiosqlite:///./dev.sqlite3 uv run alembic revision --autogenerate -m "describe the change"
```

### Frontend

The frontend needs Node 24.

```sh
cd frontend
npm ci
npm run test
npm run lint
npm run build
```

This project uses a recent Next.js version. Before you change the frontend, read `frontend/AGENTS.md` and the docs in `frontend/node_modules/next/dist/docs/`.

## Configuration

| File | What it holds |
|---|---|
| `.env` | Secrets and service addresses. `.env.example` explains each value. |
| `backend/app/providers.yaml` | The provider presets: base URL, the link to get a key, the data-handling notice, and what each provider reports. `PROVIDERS_CONFIG_PATH` points to another file. |
| `backend/app/chat/chat.yaml` | The chat settings users cannot change: the temperature range, the reply length limit, the tool round limit, and the reasoning efforts each model accepts. `CHAT_CONFIG_PATH` points to another file. |
| `backend/app/connectors.yaml` | The operator's MCP connectors and the catalog of known servers, read only when `MCP_ENABLED=true`. `MCP_CONNECTORS_PATH` points to another file. See [docs/connectors.md](docs/connectors.md). |

The backend refuses to start when one of these files is not valid. The server configuration never chooses a model for a user.

Set `ALLOW_CUSTOM_PROVIDER=false` to stop users from adding their own base URL, for example on a public demo.

## Project layout

```
backend/
  app/
    chat/        the chat: commands, prompt, tools, tool loop, event stream
    models/      SQLAlchemy tables
    routers/     API endpoints
  alembic/       migrations
  tests/
frontend/
  app/           pages: /app (chat), /app/[id], /settings
  components/    chat UI, settings sections, shadcn components
  lib/           API clients and the event stream parser
scripts/         init-env.sh: creates .env with new secrets; bundle-images.sh and
                 offline-check.sh for offline installs
deploy/offline/  the offline providers file and the offline check's files
docs/            login, setup, offline install, and search guides
openspec/        specs and planned changes
```

## How changes are planned

Work is planned with [OpenSpec](https://github.com/Fission-AI/OpenSpec). Each change in `openspec/changes/` has a proposal, a design, specs, and a task list. The specs of finished changes live in `openspec/specs/`.

`model-providers` and `conversation-agent` are done. The next change is `auth-modes`. After it come `thought-storage`, `push-and-pull`, `explore`, `mcp-connectors`, and `self-hosting-setup`.
