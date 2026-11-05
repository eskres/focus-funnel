# Offline install

This page installs Focus Funnel on a host with no internet: an air-gapped machine, or one on a closed network. The images are built and the models are downloaded on an online machine, then copied over as files. On the offline host, a local [Ollama](https://ollama.com) server answers chat and search, and Pocket ID handles login. Nothing calls out while the app runs.

The files involved:

| File | What it does |
|---|---|
| `scripts/bundle-images.sh` | builds the app's images, pulls the others, and saves them all into one archive |
| `docker-compose.offline.yml` | runs Ollama next to the app, and points the backend at the offline providers file |
| `deploy/offline/providers.yaml` | the providers file, with one preset: the local Ollama server, which needs no key |
| `docker-compose.pocket-id.yml` | runs Pocket ID with its outbound calls turned off |
| `scripts/offline-check.sh` | proves the app runs with no way out of its network |

The commands below use the three compose files of an offline install. To avoid typing them each time, set them once in `.env` (see [docs/setup.md](setup.md#2-use-the-same-compose-files-for-every-command)):

```sh
COMPOSE_FILE=docker-compose.yml:docker-compose.offline.yml:docker-compose.pocket-id.yml
```

## On the online machine

### 1. Bundle the images

From the checkout, with Docker and the internet:

```sh
scripts/bundle-images.sh
sha256sum -c focus-funnel-images-local.tar.gz.sha256
```

The script builds `focus-funnel-backend` and `focus-funnel-frontend`, pulls Postgres, Ollama, and Pocket ID, and saves all five images into `focus-funnel-images-local.tar.gz`, next to a `.sha256` file. It needs no `.env`. Set `FOCUS_FUNNEL_TAG` to name the images and the archive with your own tag instead of `local`; set the same `FOCUS_FUNNEL_TAG` in `.env` on the offline host.

The frontend's fonts are downloaded while the image is built and served by the app itself, so no page asks Google for them. Next.js telemetry is turned off in the image.

`-f` replaces the default overlays. For example, `scripts/bundle-images.sh -f docker-compose.offline.yml` bundles an install without Pocket ID.

### 2. Pull the models

The offline overlay keeps Ollama's models in `.data/ollama`. Fill it on the online machine with the same compose files:

```sh
docker compose -f docker-compose.yml -f docker-compose.offline.yml up -d ollama
docker compose -f docker-compose.yml -f docker-compose.offline.yml exec ollama ollama pull qwen3:1.7b
docker compose -f docker-compose.yml -f docker-compose.offline.yml exec ollama ollama pull nomic-embed-text:v1.5
docker compose -f docker-compose.yml -f docker-compose.offline.yml stop ollama
```

- The chat model must call tools, because filing and search are tool calls. `qwen3:1.7b` is small. A larger model, such as `qwen3:8b`, files and searches more reliably if the host has the memory. Pull every chat model your users should be able to choose.
- `nomic-embed-text:v1.5` is the overlay's search (embedding) model. To use another one, pull it and set `OFFLINE_EMBEDDING_MODEL` in `.env` before anyone files a thought. A search index keeps the model it was built with until the operator rebuilds it (`python -m app.reembed`, see [docs/search.md](search.md)).

### 3. Copy everything over

Copy these to the offline host, for example on a USB drive:

- the checkout, without `.env` and `.data/postgres`
- `focus-funnel-images-local.tar.gz` and its `.sha256` file
- `.data/ollama`, to the same place in the checkout (`tar -C .data -cf ollama.tar ollama` keeps it in one file)

## On the offline host

### 4. Load the images

```sh
sha256sum -c focus-funnel-images-local.tar.gz.sha256
gunzip -c focus-funnel-images-local.tar.gz | docker load
```

### 5. Generate `.env`

```sh
scripts/init-env.sh --auth-mode oidc
```

Then add to `.env`:

```sh
COMPOSE_FILE=docker-compose.yml:docker-compose.offline.yml:docker-compose.pocket-id.yml
SETUP_WIZARD=false
```

`SETUP_WIZARD=false` skips the setup wizard. Nobody needs it here: the local preset needs no key, so every user can choose an Ollama model in **Settings** right away, and the doctor (step 8) checks the install. You can also leave the wizard on and finish it at `/setup` as [docs/setup.md](setup.md) describes; its provider step then has no key to save.

The offline overlay turns the custom provider off, so the provider list offers only the local Ollama server. Set `ALLOW_CUSTOM_PROVIDER=true` in `.env` to let users add another OpenAI-compatible server on your network.

### 6. Set up Pocket ID

Login uses an OpenID Connect issuer inside the install: Pocket ID, from `docker-compose.pocket-id.yml`. The overlay turns off its two outbound calls, the analytics heartbeat (`ANALYTICS_DISABLED=true`) and the release check against GitHub (`VERSION_CHECK_DISABLED=true`), so Pocket ID also makes no call outside the install.

Start Pocket ID on its own and register the app as a client, as steps 3 to 6 of [Pocket ID in docs/login.md](login.md#pocket-id) describe:

```sh
docker compose -f docker-compose.yml -f docker-compose.offline.yml -f docker-compose.pocket-id.yml up -d --no-build --pull never pocket-id
```

Then fill `OIDC_ISSUER=http://localhost:1411`, `OIDC_CLIENT_ID`, and `OIDC_CLIENT_SECRET` in `.env`.

`firebase` mode cannot work offline. Firebase signs users in on Google's servers, and both servers fetch Google's signing keys and refresh tokens there. Use `oidc` with Pocket ID instead.

### 7. Start

```sh
docker compose -f docker-compose.yml -f docker-compose.offline.yml -f docker-compose.pocket-id.yml up -d --no-build --pull never
```

`--no-build --pull never` makes compose use only the loaded images. With `SETUP_WIZARD=false`, the backend prints no setup token, and `/setup` says that setup is not open.

Open http://localhost:3000, log in with your passkey, and choose an Ollama model as the default in **Settings**. Chat, file a thought with `/push`, and find it again with `/pull`.

### Using the app from another machine

Passkeys, and the app's `Secure` cookies, work only on `localhost` or HTTPS. The simplest choice is a browser on the offline host itself, at `http://localhost:3000` and `http://localhost:1411`.

A browser on another machine that opens `http://<host address>:3000` over plain HTTP cannot log in. Put HTTPS in front of the app instead, with a local certificate authority: Caddy with `tls internal`, as [HTTPS on your network](login.md#https-on-your-network) describes. Bring the Caddy binary or image along from the online machine. Each device must trust Caddy's root certificate once, because no public certificate authority can be reached.

### 8. Check the install with the doctor

Run the doctor with the same compose files as the install:

```sh
docker compose -f docker-compose.yml -f docker-compose.offline.yml -f docker-compose.pocket-id.yml run --rm --entrypoint python backend -m app.doctor; echo $?
```

It prints 0 when nothing failed. Its provider line for Ollama shows how many models the server has and whether the search model is among them; a missing search model means the models were not copied into `.data/ollama`. See [The doctor](setup.md#the-doctor) for the rest.

## Connectors

Connectors (`MCP_ENABLED=true`) work offline only when the connector server runs inside the install: an operator connector run as a sidecar on the compose network, with its own compose overlay (the pattern of `docker-compose.mcp.yml`, though its Google Calendar server itself needs Google's API and so does not work offline) and its image bundled with `scripts/bundle-images.sh -f`. Its token goes in `.env`, under the name its `auth.env` gives in `connectors.yaml`; the setup script does not generate it. A connector at an outside URL, including any connector a user adds, cannot be reached. The doctor shows each operator connector as reachable or not. [docs/connectors.md](connectors.md) has the settings, `connectors.yaml`, and the overlay.

## The offline check

The offline check proves that the app runs with no way out of its network. Run it on an online machine before you bundle a release:

```sh
scripts/offline-check.sh
```

It builds the images, then starts the app in demo mode on a compose network marked `internal`, with a stand-in model server on that network, without building or pulling anything more. A smoke test inside the network then runs seven steps and prints each one:

1. An outside address (`example.com`, `1.1.1.1`) cannot be reached.
2. A page starts a demo session.
3. The page and its stylesheets load scripts, styles, and fonts only from the app, and name no font service.
4. The stand-in model is chosen as the default.
5. `/push` gives a proposal, and confirming it files a thought.
6. `/pull` finds that thought.
7. The stand-in served the model list, the chat, and the embeddings.

It exits 0 when every step passes, and 1 otherwise, naming the step that failed. It never reads your `.env`, and it removes its containers and data when it ends. `--no-build` uses the images already built. `-f file` adds a compose file to every call; for example, `scripts/offline-check.sh -f deploy/offline/check/not-internal.yml` runs it on an ordinary network, and step 1 then fails with "the network is not internal".

Demo mode needs no login, so the check covers every path that could call out except login. The manual run above, with Pocket ID on an offline host, covers login.
