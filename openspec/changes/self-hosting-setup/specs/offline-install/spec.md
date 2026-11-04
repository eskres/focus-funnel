# Spec Delta

## Purpose

Lets an operator check an install from the command line, and run the app with no internet: images moved by file, a local model server for chat and search, no runtime call outside the install, and a repeatable check that proves it.

## ADDED Requirements

### Requirement: The doctor command checks an install

The backend SHALL provide a `doctor` command that runs in the backend image without starting the server. It SHALL print one line per check with its state (`ok`, `missing`, `failed`, `warning`, `info`, or `skipped`) and a message, using the same instance-wide items and messages as the setup status. It SHALL exit with status 0 when no check failed and 1 otherwise, and with `--json` print the same checks as JSON. Each check SHALL give up after 5 seconds.

#### Scenario: A healthy install

- **WHEN** the operator runs the doctor on an install whose settings are valid, whose database answers with pgvector, and whose embedding provider answers
- **THEN** it prints a line per check and exits with status 0

#### Scenario: The database is down

- **WHEN** the operator runs the doctor while Postgres is stopped
- **THEN** the `database` line is `failed` with a message that it could not connect
- **AND** the doctor exits with status 1 within the time limit

#### Scenario: Settings that stop the server

- **WHEN** the operator runs the doctor with `AUTH_MODE` unset
- **THEN** a `failed` line names `AUTH_MODE` and that it must be `oidc`, `firebase`, or `demo`
- **AND** the checks that need valid settings are `skipped`, and the database is still checked

#### Scenario: A database not migrated yet

- **WHEN** the operator runs the doctor against a reachable Postgres with pgvector available but no migrations applied
- **THEN** the database, migrations, and setup lines are warnings that say the database is not migrated yet, not failures
- **AND** the doctor exits with status 0 if nothing else failed

#### Scenario: Unreachable embedding provider

- **WHEN** the embedding provider's address does not answer
- **THEN** its line is `failed`, because search cannot work
- **AND** an unreachable preset that is not the embedding provider is a `warning`

### Requirement: The doctor checks connections and configuration

Besides the setup status items, whose login item it reports as `info` because it has no logged-in user, the doctor SHALL check that the settings and configuration files load, whether the database schema is at the latest migration, whether setup is open, closed, or off, that the login provider answers (`oidc`: the issuer's discovery document, with an issuer equal to `OIDC_ISSUER`; `firebase`: Google's signing keys), and that each provider preset and each operator connector answers.

#### Scenario: Issuer not reachable

- **WHEN** `AUTH_MODE=oidc` and the issuer's discovery document cannot be fetched
- **THEN** the login provider line is `failed` and names the address it tried, which is the `OIDC_INTERNAL_URL` address when that is set

#### Scenario: Migrations behind

- **WHEN** the database schema is older than the latest migration
- **THEN** the migrations line is a `warning` that says the backend applies them when it starts

### Requirement: The doctor prints no secrets

The doctor SHALL NOT print a provider key, the key encryption key, the session secret, the client secret, the setup token, the database password, or a connector's credentials, in its lines or its JSON. A settings error SHALL name the variable and the rule it breaks without its value, and a URL SHALL be shown without userinfo or query string.

#### Scenario: No secrets in the output

- **WHEN** the doctor prints the database line
- **THEN** the database URL is shown with its password masked
- **AND** no line contains the key encryption key, the session secret, or the setup token

#### Scenario: An invalid secret

- **WHEN** the doctor runs with a `KEY_ENCRYPTION_KEY` that does not decode to 32 bytes
- **THEN** a `failed` line names `KEY_ENCRYPTION_KEY`
- **AND** neither the text nor the `--json` output contains its value

#### Scenario: A connector URL with credentials

- **WHEN** an operator connector's URL holds a user name and password or a token in its query string
- **THEN** the connector line names the connector with the URL's scheme, host, and port only

### Requirement: No runtime calls to the internet

With an offline providers file, `AUTH_MODE=oidc` against an issuer inside the install, and no connector outside it, neither server SHALL make any network call outside the install while it runs. The frontend image SHALL be built and run with Next.js telemetry turned off. Every page SHALL load its fonts, scripts, and styles from the app's own address, and SHALL NOT reference a font service or other outside host.

#### Scenario: Pages use only the app's address

- **WHEN** a page of the app is loaded
- **THEN** every script, style, and font it loads is served by the app
- **AND** neither the page nor its styles reference `fonts.googleapis.com` or `fonts.gstatic.com`

#### Scenario: Telemetry is off

- **WHEN** the frontend image runs
- **THEN** `NEXT_TELEMETRY_DISABLED` is set to `1` in its environment

### Requirement: Images move to an offline host as files

The repository SHALL provide a script that builds the app's images, pulls the other images an install uses, and saves them all into one archive with `docker save`, and that runs on a build machine with no `.env`. The compose files SHALL give the app's images fixed names, so a host that loaded the archive with `docker load` can start the install with no build and no pull.

#### Scenario: Load and start offline

- **WHEN** the archive is loaded on a host with no internet and the install is started with `--no-build --pull never`
- **THEN** every service starts from the loaded images

### Requirement: A local model server serves chat and search

The repository SHALL provide an offline providers file whose only preset is a local model server that needs no key, and a compose overlay that runs that server and points the backend at the file, with the embedding provider set to that preset. With them, a user SHALL be able to choose a chat model, chat, file a thought, and find it again with no key and no internet.

#### Scenario: A keyless local provider

- **WHEN** the backend runs with the offline overlay
- **THEN** the provider list offers only the local server, marked as needing no key
- **AND** the setup status's `search_key` item is `ok` for every user

### Requirement: The offline check proves an install runs without the internet

The repository SHALL provide an offline check that starts the app in demo mode on a compose network marked `internal`, with a stand-in model server on that network, and runs a smoke test from inside the network. It SHALL start the services without building or pulling, use none of the operator's `.env` values, exit with status 0 only when every step passes, name the step that failed otherwise, and remove its containers and data when it ends.

#### Scenario: The check passes

- **WHEN** the operator runs the offline check on a checkout whose images are built
- **THEN** every step passes and the check exits with status 0

### Requirement: The smoke test's steps

The smoke test SHALL first confirm that an outside address cannot be reached. It SHALL then load a page and check that it references no outside host, choose a model, send a `/push` message, confirm the proposal, find the thought with `/pull`, and confirm that the stand-in served the model list, the chat, and the embedding calls.

#### Scenario: A network that is not internal

- **WHEN** the smoke test can reach an outside address
- **THEN** it fails at its first step, saying the network is not internal

#### Scenario: A runtime call to the internet

- **WHEN** the backend in the check is pointed at a provider outside the install
- **THEN** the check fails and names the step that needed it

### Requirement: The offline install guide

The documentation SHALL include an offline install guide that covers: building and moving the images, getting the local model server's models onto the offline host, the offline overlay and providers file, skipping the wizard, the doctor with the same compose files as the install, and the offline check.

#### Scenario: Follow the guide

- **WHEN** an operator follows the guide on a host with no internet
- **THEN** they can log in, chat, file a thought, and find it again
- **AND** with `SETUP_WIZARD=false`, a second user can choose the local model and chat without saving a key

### Requirement: The offline guide covers login and connectors

The offline install guide SHALL explain login with an issuer inside the install (Pocket ID) with its outbound calls turned off, that the browser must reach the app over `localhost` or HTTPS, that `firebase` mode cannot work offline, and that connectors work only inside the install, with their tokens in `.env`.

#### Scenario: A browser on another machine

- **WHEN** an operator reads the guide to log in from a machine other than the offline host
- **THEN** the guide tells them to put HTTPS with a local certificate authority in front of the app, because plain HTTP to the host's address cannot log in
