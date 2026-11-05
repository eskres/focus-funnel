# Spec Delta

## Purpose

Gives a first-time operator one path through what a new install needs: the login settings, the bootstrap secrets, a provider key, a default model, and a working database. It reports what is missing and sets nothing the settings screens cannot set.

## ADDED Requirements

### Requirement: Setup is open only on a first run

Setup SHALL be open when the instance's setup record exists and has not finished, the auth mode is `oidc` or `firebase`, and `SETUP_WIZARD` is not set to `false`. A missing setup record SHALL count as closed, and the server SHALL NOT create it outside the migration. While setup is closed, every setup route SHALL respond with HTTP 404 and error code `not_found`.

#### Scenario: A new install

- **WHEN** the server starts for the first time with `AUTH_MODE=oidc` and an empty database
- **THEN** setup is open

#### Scenario: Turned off by the operator

- **WHEN** the server starts with `SETUP_WIZARD=false`
- **THEN** setup is closed and no setup token is printed
- **AND** `GET /api/setup/status` responds with HTTP 404 and error code `not_found`

#### Scenario: The setup record is missing

- **WHEN** the server starts on a migrated database whose setup record was deleted
- **THEN** setup is closed, no setup token is printed, and the record is not created again

### Requirement: Demo mode and installs in use never open setup

Setup SHALL never be open in demo mode, and the server SHALL refuse to start in demo mode when `SETUP_WIZARD=true` is set explicitly, naming the setting. An install that already has any user when this change is deployed SHALL count as having finished setup.

#### Scenario: Demo mode

- **WHEN** the server starts in demo mode without `SETUP_WIZARD`
- **THEN** setup is closed

#### Scenario: Demo mode with the wizard asked for

- **WHEN** the server starts in demo mode with `SETUP_WIZARD=true`
- **THEN** it refuses to start and names `SETUP_WIZARD`

#### Scenario: An install already in use

- **WHEN** the change is deployed on a database that has at least one user, with or without a default chat model
- **THEN** setup is closed and no setup token is printed

### Requirement: The server prints a new setup token at each start

While setup is open, the server SHALL generate a new random setup token with at least 192 bits of entropy each time it starts, print it to its log once per start with the address of the app's `/setup` page, and store only a hash of it. The token SHALL stay valid until the next start or until setup finishes, and SHALL be compared in constant time. A token printed at an earlier start SHALL stop working. No API response SHALL contain the token.

#### Scenario: The token is printed at start

- **WHEN** the server starts while setup is open
- **THEN** its log holds the setup token and tells the operator to open the app's `/setup` page, with `APP_BASE_URL` when it is set
- **AND** the database holds a hash of the token, not the token

#### Scenario: A restart replaces the token

- **WHEN** the server restarts while setup is open
- **THEN** it prints a new token
- **AND** a setup request with the old token is refused with HTTP 403 and error code `setup_token_invalid`

### Requirement: Setup routes need a login and the token

Every setup route SHALL require a logged-in user and the current setup token, sent in the `X-Setup-Token` header. A missing, empty, or wrong token SHALL be refused with HTTP 403 and error code `setup_token_invalid`, with the same message. While setup is open but no token hash is stored, every token SHALL be refused the same way. The app's API proxy SHALL forward the header only to setup routes.

#### Scenario: Logged in without the token

- **WHEN** a logged-in user requests `GET /api/setup/status` without the `X-Setup-Token` header
- **THEN** the system responds with HTTP 403 and error code `setup_token_invalid`

#### Scenario: The token without a login

- **WHEN** a request with the right token but no login reaches a setup route
- **THEN** the system responds with HTTP 401 and error code `unauthenticated`

#### Scenario: No token stored yet

- **WHEN** setup is open, no token hash is stored, and a logged-in user sends any token
- **THEN** the system responds with HTTP 403 and error code `setup_token_invalid`

#### Scenario: The header stays on setup routes

- **WHEN** the browser sends `X-Setup-Token` with a request for a route that is not a setup route
- **THEN** the app's API proxy does not forward the header to the backend

### Requirement: The status endpoint reports what is missing

`GET /api/setup/status` SHALL return the auth mode, a `ready` flag, and a list of items. Each item SHALL have an id, a state (`ok`, `missing`, `failed`, `warning`, or `info`), whether it is required, a message in plain words, and the names of the environment variables that set it. `ready` SHALL be true only when every required item is `ok`.

#### Scenario: A fresh install

- **WHEN** the operator requests the status after logging in for the first time
- **THEN** `database`, `encryption_key`, and `login` are `ok`
- **AND** `search_key` and `chat_model` are `missing`
- **AND** `ready` is false

### Requirement: The status items

The status SHALL hold these items: `database` (Postgres answers and has pgvector), `encryption_key`, `login` (the auth mode and its settings), `allow_list`, `search_key` (the requesting user can use the embedding provider), `chat_model` (the requesting user has a default chat model whose provider they can use), `custom_provider`, and `connectors`. Only `database`, `encryption_key`, `login`, `search_key`, and `chat_model` SHALL be required.

#### Scenario: No allow-list

- **WHEN** `AUTH_ALLOWED_EMAILS` is not set
- **THEN** the `allow_list` item is a `warning` that says anyone the login provider lets in can use the instance
- **AND** it is not required

#### Scenario: Search needs a key for the embedding provider

- **WHEN** `EMBEDDING_PROVIDER` is a preset that needs a key and the user has saved a key only for another provider
- **THEN** the `search_key` item is `missing` and names the embedding provider

#### Scenario: A provider that needs no key

- **WHEN** `EMBEDDING_PROVIDER` is a preset configured with no key required
- **THEN** the `search_key` item is `ok` without a saved key

#### Scenario: A saved key the server cannot read

- **WHEN** the user's saved key for the embedding provider no longer decrypts with the current key encryption key
- **THEN** the `search_key` item is `failed` and says the saved key cannot be read with the current `KEY_ENCRYPTION_KEY`

#### Scenario: A default model whose provider is gone

- **WHEN** the user's default model belongs to a provider that is no longer in the providers file, or to the custom provider while custom providers are turned off
- **THEN** the `chat_model` item is `missing` with a message that names the provider
- **AND** the status still responds with HTTP 200

### Requirement: The status holds no secrets and calls nothing outside

The status SHALL NOT contain any secret value: no provider key, key encryption key, session secret, client secret, database password, or setup token. A URL in a message SHALL show no userinfo and no query string, and a database failure SHALL be described with a fixed message, not the driver's error text. Building the status SHALL make no call outside the server and its database.

#### Scenario: No secrets in the status

- **WHEN** the status is returned in `oidc` mode for a user with a saved provider key
- **THEN** it names the issuer and the client id
- **AND** it contains neither the client secret, the key encryption key, the provider key, nor the setup token

### Requirement: Login settings come from the environment

The auth mode, its settings, and the email allow-list SHALL be set only through environment variables, because both servers check them before they start. The wizard SHALL show the auth mode in use, the non-secret values of its settings, and the allow-list, SHALL name the variables that change them, and SHALL NOT offer to change them.

#### Scenario: The wizard shows the login step

- **WHEN** the operator opens the login step in `oidc` mode
- **THEN** it shows the mode, the issuer, the client id, and the allow-list entries or that none is set
- **AND** it names `AUTH_MODE`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and `AUTH_ALLOWED_EMAILS` as the settings to change in the environment
- **AND** it has no field to change them

### Requirement: The wizard sets the provider and model through the settings

The wizard's provider and model steps SHALL offer the same choices, links, notices, key check, model list, efforts, and Test as the settings. What they save SHALL be the logged-in user's own key and models, stored as the settings store them, with the key encrypted. The provider step SHALL say which provider search uses. The status SHALL change as soon as a save succeeds.

#### Scenario: Save a key in the wizard

- **WHEN** the operator saves a Nebius key in the wizard's provider step
- **THEN** the key is checked with Nebius and stored encrypted for that user, as the provider settings would store it
- **AND** the settings page shows the same key afterwards

#### Scenario: A refused key

- **WHEN** the provider refuses the key
- **THEN** the wizard shows the same message the provider settings show, and nothing is stored

#### Scenario: Status follows the steps

- **WHEN** the operator saves a default model in the model step
- **THEN** the `chat_model` item shows as `ok` without reloading the page

### Requirement: Finishing setup closes it

`POST /api/setup/complete` SHALL close setup when the requesting user's status is `ready`, discard the stored token hash, and respond with HTTP 204. When a required item is not `ok`, it SHALL respond with HTTP 409 and error code `setup_incomplete`, naming the first missing item, and leave setup open. Once closed, setup SHALL stay closed across restarts, and no route SHALL open it again.

#### Scenario: Finish

- **WHEN** the operator finishes setup with every required item `ok`
- **THEN** the system responds with HTTP 204
- **AND** a later `GET /api/setup/status` with the same token responds with HTTP 404 and error code `not_found`
- **AND** the next start prints no setup token

#### Scenario: Finish too early

- **WHEN** the operator finishes setup while `chat_model` is `missing`
- **THEN** the system responds with HTTP 409 and error code `setup_incomplete`, naming the default model
- **AND** setup stays open

#### Scenario: Two finishes at once

- **WHEN** two finish requests arrive at the same time
- **THEN** one responds with HTTP 204 and the other with HTTP 404 and error code `not_found`

### Requirement: The wizard page

The app SHALL serve the wizard at `/setup` to logged-in users. The page SHALL ask for the setup token, then show four steps (login, provider, model, and server) with each item's state and message, and a Finish button enabled only when the status is `ready`. When setup is closed, the page SHALL say so and link to the settings. The page SHALL keep the token only for the browser tab and forget it after Finish, after a refused token, and when setup is closed.

#### Scenario: Logged out

- **WHEN** a logged-out person opens `/setup`
- **THEN** they are sent to log in and come back to `/setup`

#### Scenario: Setup closed

- **WHEN** a logged-in user opens `/setup` after setup has finished
- **THEN** the page says setup is not open and links to the settings

#### Scenario: A wrong token

- **WHEN** the operator enters a token the server refuses
- **THEN** the page shows the refusal, forgets the token, and asks for it again

#### Scenario: Finish from the page

- **WHEN** every required item is `ok` and the operator clicks Finish
- **THEN** the page says setup is complete and links to the app

### Requirement: A setup script generates the bootstrap secrets

The repository SHALL provide a setup script that creates `.env` from `.env.example` when it is missing and sets new random bootstrap secrets: the key encryption key, the session secret, the Pocket ID encryption key, and a Postgres password with the matching database URL. It SHALL take the auth mode as an option, and SHALL print the names it set (never the values), the settings the mode still needs, and a reminder to keep a copy of the key encryption key.

#### Scenario: First run of the script

- **WHEN** the operator runs the script with `--auth-mode oidc` in a checkout without `.env`
- **THEN** `.env` exists with a 32-byte base64 key encryption key, a session secret, a Postgres password used by the database URL, and `AUTH_MODE=oidc`
- **AND** the script names `OIDC_ISSUER`, `OIDC_CLIENT_ID`, and `OIDC_CLIENT_SECRET` as still to fill

### Requirement: The setup script protects the secrets it writes

The `.env` the setup script writes SHALL be readable only by its owner, and the script SHALL leave no temporary copy of the secrets behind, even when it is interrupted.

#### Scenario: File mode

- **WHEN** the script creates or changes `.env`
- **THEN** `.env` has file mode 600

#### Scenario: Interrupted

- **WHEN** the script is stopped while it writes `.env`
- **THEN** no temporary file holding a secret is left behind

### Requirement: The setup script never changes a value that is set

On an existing `.env`, the setup script SHALL fill only bootstrap secrets that are empty, and the auth mode only when it is empty. It SHALL NOT change any value that is set, and SHALL NOT change the Postgres password or the database URL, even when they are empty. Without `.env`, when the Postgres data directory already holds a database, it SHALL keep the example's Postgres password and database URL and warn.

#### Scenario: Run again

- **WHEN** the script runs on a `.env` whose key encryption key and Postgres password are set and whose session secret is empty
- **THEN** it fills the session secret
- **AND** the key encryption key, the Postgres password, and the database URL do not change

#### Scenario: A mode already set

- **WHEN** the script runs with `--auth-mode firebase` on a `.env` with `AUTH_MODE=oidc`
- **THEN** `AUTH_MODE` stays `oidc`

#### Scenario: Postgres data already exists

- **WHEN** the script runs without `.env` in a checkout whose Postgres data directory is not empty
- **THEN** `.env` keeps the example's Postgres password and database URL
- **AND** the script warns that the existing database still uses that password

### Requirement: The environment can set up an install without the wizard

Every instance-wide option the wizard shows SHALL be set only through environment variables or the files they point to, so the wizard never overrides the environment. A user's provider keys and models SHALL stay per user and SHALL NOT be set from the environment. `SETUP_WIZARD=false` SHALL skip the wizard, and a providers file whose provider needs no key SHALL need no key from any user: the model settings SHALL offer that provider's models to a user who never saved it.

#### Scenario: Skip the wizard

- **WHEN** a compose install sets the login settings, the bootstrap secrets, a providers file with a keyless local provider, and `SETUP_WIZARD=false`
- **THEN** the server starts with setup closed
- **AND** a new user can choose a model and chat without saving any key
