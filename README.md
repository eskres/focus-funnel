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

Not built yet: saving and searching thoughts, `/compact`, the context meter, and usage tracking. For now, the search tool and the Confirm button answer that the feature is not available yet.

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

You need Docker. Login is set up with `AUTH_MODE` in `.env`: an OpenID Connect provider, a Firebase project, or an anonymous demo. [docs/login.md](docs/login.md) explains each one. The quickest start is Pocket ID, which runs next to the app:

1. Copy `.env.example` to `.env`.
2. Follow [Pocket ID in docs/login.md](docs/login.md#pocket-id). It generates the secrets, starts everything with `docker-compose.pocket-id.yml`, and registers the app with Pocket ID.
3. Open http://localhost:3000 and log in with your passkey.
4. In **Settings**, save an API key for a provider.
5. In **Settings**, add a chat model and mark it as the default. The Test button checks that the model answers and can call a tool.

Without the Pocket ID overlay, start everything with:

```sh
docker compose up --build
```

The backend applies database migrations each time it starts. Postgres keeps its data in `.data/`.

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

The tests use SQLite by default. To run them against Postgres, set `TEST_DATABASE_URL`, for example to the compose Postgres from `docker-compose.dev.yml`:

```sh
TEST_DATABASE_URL=postgresql+asyncpg://focus_funnel:focus_funnel@localhost:55432/focus_funnel uv run pytest
```

Thought storage and search need Postgres with pgvector, so their tests are marked `postgres` and left out of the runs above. Run them on their own, against a Postgres that has the `vector` extension, such as the compose one:

```sh
TEST_DATABASE_URL=postgresql+asyncpg://focus_funnel:focus_funnel@localhost:55432/focus_funnel uv run pytest -m postgres
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
openspec/        specs and planned changes
```

## How changes are planned

Work is planned with [OpenSpec](https://github.com/Fission-AI/OpenSpec). Each change in `openspec/changes/` has a proposal, a design, specs, and a task list. The specs of finished changes live in `openspec/specs/`.

`model-providers` and `conversation-agent` are done. The next change is `auth-modes`. After it come `thought-storage`, `push-and-pull`, `explore`, `mcp-connectors`, and `self-hosting-setup`.
