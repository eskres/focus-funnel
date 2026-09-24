> **Planning status:** Proposal only. Write the specs, design, and tasks when this change is picked up. Depends on `auth-modes` and `model-providers`.

## Why

A self-hoster must set an auth mode, generate secrets, add a provider key, and pick models before anything works. The app already explains each missing piece where it fails, but a first-time user has no single path through them. Some installs are also air-gapped and need to check that nothing reaches the internet.

## What Changes

- Add a first-run setup wizard that walks through the same settings the app already has:
  1. Choose the auth mode and enter its settings (for `oidc`: issuer, client id and secret; for `firebase`: project settings). Optionally set an email allow-list.
  2. Add a provider and its key from the presets, with the provider's "get a key" link and notice, or a custom local server such as Ollama. A Test lists models.
  3. Choose the default model and loadout, with the effort options and the Test from `conversation-agent`.
  4. Check that Postgres is reachable and has the pgvector extension.
- The wizard is a checklist over a status endpoint, `GET /api/setup/status`, that reports what is missing. It uses the same APIs as the settings screens and has no logic of its own.
- Protect setup mode. The server prints a one-time setup token in its log at first run, the wizard requires it, and the wizard locks when setup completes. It is never left open.
- Keep bootstrap secrets in the environment: the database URL and the key-encryption key, which a setup script or compose step can generate. Everything the wizard chooses is stored in the database, with secrets encrypted by that key.
- Let every wizard option also be set through environment variables, so Docker and CI installs can skip the wizard.
- Add a `doctor` command that prints the same status from the command line and checks connections to the database and the provider.
- Add an offline install guide and an offline check for air-gapped installs: images bundled with `docker save`, a local model provider, no runtime calls to the internet (telemetry off, no CDN fonts), and a smoke test on a compose network marked `internal` to prove it.

## Capabilities

### New Capabilities

- `setup-wizard`: The first-run checklist, the status endpoint, the setup token, the lock, and the environment-variable path.
- `offline-install`: The `doctor` command, the offline install guide, and the offline check.

### Modified Capabilities

None expected.

## Impact

- **Backend:** the status endpoint, the setup-mode token and lock, environment-variable reading for wizard options, and the `doctor` command.
- **Frontend:** the wizard screens, reusing the provider and model settings components.
- **Deployment:** a setup script for bootstrap secrets, a compose overlay for an internal network, and the offline guide.
- **Out of scope:** installing or configuring an identity provider for the user. The wizard only asks for its settings.
