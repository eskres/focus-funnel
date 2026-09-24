# Login setup

Focus Funnel has three ways to log in. You choose one with `AUTH_MODE` in `.env`. The frontend and the backend both refuse to start when `AUTH_MODE` is missing or wrong, or when a setting that the mode needs is missing, and the error names the setting.

| `AUTH_MODE` | Who logs in | Use it for |
|---|---|---|
| `oidc` | Anyone your OpenID Connect provider logs in: Pocket ID, Authentik, Keycloak, Auth0, and others | Self-hosting |
| `firebase` | Anyone your Firebase project logs in, with Google or email and password | Hosting on the web |
| `demo` | Nobody logs in. Each visitor gets an anonymous session that expires | A public, throwaway demo |

There is no mode without login that keeps data. Only `demo` has no login, and its data expires.

Every mode needs `SESSION_SECRET`. It seals the cookies the frontend server sets:

```sh
openssl rand -hex 32
```

In every mode, login tokens stay on the server. The browser holds only encrypted, HttpOnly cookies that page scripts cannot read.

These cookies are marked `Secure`. Browsers accept them on `http://localhost` and on HTTPS, but not on a plain-HTTP address such as `http://192.168.1.20:3000`. To use Focus Funnel from other devices on your network, put HTTPS in front of it (see [HTTPS on your network](#https-on-your-network)).

## Pocket ID

[Pocket ID](https://pocket-id.org) is a small OpenID Connect provider that logs people in with passkeys. `docker-compose.pocket-id.yml` runs it next to Focus Funnel, pinned to `ghcr.io/pocket-id/pocket-id:v2.16.0`. Its data is stored in `.data/pocket-id`.

1. Copy `.env.example` to `.env` if you have not already.
2. Generate the secrets and put them in `.env`:

   ```sh
   openssl rand -hex 32      # SESSION_SECRET
   openssl rand -base64 32   # KEY_ENCRYPTION_KEY
   openssl rand -base64 32   # POCKET_ID_ENCRYPTION_KEY
   ```

3. Start everything with the Pocket ID overlay:

   ```sh
   docker compose -f docker-compose.yml -f docker-compose.pocket-id.yml up --build
   ```

   The backend and the frontend stop at once because `AUTH_MODE` is not set yet. That is expected; Pocket ID keeps running.
4. Open http://localhost:1411/setup, create the admin account, and add a passkey.
5. In Pocket ID, open **OIDC Clients** and add a client:
   - **Name:** Focus Funnel
   - **Callback URLs:** `http://localhost:3000/auth/callback`
   - **Logout Callback URLs:** `http://localhost:3000/`
   - Leave **Public Client** off, so the client has a secret.
6. Copy the client ID and the client secret into `.env`, and set the mode:

   ```sh
   AUTH_MODE=oidc
   OIDC_ISSUER=http://localhost:1411
   OIDC_CLIENT_ID=<client id>
   OIDC_CLIENT_SECRET=<client secret>
   ```

   Leave `OIDC_INTERNAL_URL` empty. The overlay sets it to `http://pocket-id:1411`, because inside compose `localhost:1411` is the container itself. The backend and the frontend server then call Pocket ID at that address. Tokens are still checked against `OIDC_ISSUER`.
7. Restart: stop compose with Ctrl+C and run the command from step 3 again.
8. Open http://localhost:3000 and log in with your passkey.

Two Pocket ID settings can refuse everyone:

- **Unverified email.** A new Pocket ID user's email address is not verified (`email_verified: false`) until an admin marks it verified in that user's settings under **Users**. With an [allow-list](#allow-list), Focus Funnel refuses a user whose address is not verified. Without an allow-list, it does not matter.
- **Restrict to user groups.** If the OIDC client has **Restrict to user groups** turned on and no group is allowed, Pocket ID refuses every user with "You are not allowed to access this service". Turn the restriction off, or allow a group that your users belong to.

To reach Pocket ID and Focus Funnel from other devices, read [HTTPS on your network](#https-on-your-network). Passkeys work only on `localhost` or HTTPS.

## Another OpenID Connect provider

Any provider that publishes a discovery document (`<issuer>/.well-known/openid-configuration`) works through the same settings. Authentik, Keycloak, and Auth0 are examples.

1. Create a confidential client (Authentik: "OAuth2/OpenID Provider"; Keycloak: a client with client authentication on; Auth0: a "Regular Web Application").
2. Set its redirect URI to `<APP_BASE_URL>/auth/callback`, for example `http://localhost:3000/auth/callback`, and its post-logout redirect URI to `<APP_BASE_URL>/`.
3. Set in `.env`:

   ```sh
   AUTH_MODE=oidc
   APP_BASE_URL=http://localhost:3000
   OIDC_ISSUER=<issuer>
   OIDC_CLIENT_ID=<client id>
   OIDC_CLIENT_SECRET=<client secret>
   ```

`OIDC_ISSUER` must be exactly the `iss` value in the provider's ID tokens, including any trailing slash. For Auth0 that is `https://<tenant>.auth0.com/`, with the slash. For Keycloak it is `https://<host>/realms/<realm>`.

The scopes default to `openid email profile offline_access`. `offline_access` gives a refresh token, so a session lasts past the first ID token. If your provider refuses `offline_access`, set `OIDC_SCOPES=openid email profile`; users then log in again when their ID token expires. Keep `email` in the scopes if you use an allow-list.

Set `OIDC_INTERNAL_URL` only when the containers cannot reach the issuer's public address, as with Pocket ID in compose. It replaces the issuer's origin for every call the servers make (discovery, keys, token). The browser is still sent to the public address.

The backend checks the ID token's signature, issuer, audience (the client ID), and expiry. It accepts only `RS256`, `ES256`, and `EdDSA`.

## Firebase

1. In the [Firebase console](https://console.firebase.google.com), create a project.
2. Under **Authentication**, then **Sign-in method**, turn on **Google** and **Email/Password**.
3. Under **Authentication**, then **Settings**, then **Authorized domains**, add the domain users open Focus Funnel on. `localhost` is there already.
4. Under **Project settings**, add a web app and copy its config into `.env`:

   ```sh
   AUTH_MODE=firebase
   APP_BASE_URL=http://localhost:3000
   FIREBASE_PROJECT_ID=<projectId>
   FIREBASE_API_KEY=<apiKey>
   FIREBASE_AUTH_DOMAIN=<authDomain>
   ```

Set `APP_BASE_URL` to the address users open, such as `https://focus.example.org`. The login page may only hand its tokens to the server from that address.

The web API key is public by design: it names the project and is not a secret. Focus Funnel needs no service account.

The login page at `/login` offers Google and email and password. Users with email and password are created in the Firebase console (**Authentication**, then **Users**, then **Add user**). The page signs in with in-memory persistence, hands the tokens to the frontend server, and signs out of Firebase at once, so no Firebase token stays in the browser.

An email-and-password user's address is not verified until they confirm it. With an [allow-list](#allow-list), Focus Funnel refuses that user until it is verified. Google sign-in gives verified addresses.

## Allow-list

In `oidc` and `firebase` modes, `AUTH_ALLOWED_EMAILS` limits who may use the app. It takes a comma-separated list of addresses and `@domain` entries, compared without regard to case:

```sh
AUTH_ALLOWED_EMAILS=ana@example.org,@example.com
```

- `ana@example.org` lets in that address.
- `@example.com` lets in every address at `example.com`, but not at `mail.example.com`.

When a list is set, a user gets in only when the provider says their address is verified (`email_verified: true`) and the address is on the list. Anyone else sees a page that says this instance does not accept their account, and no user record is created. The backend checks the list on every request, so after you remove an address and restart, that user's next call is refused.

When no list is set, anyone the provider logs in may use the app. With `oidc`, the provider's own access rules (such as Pocket ID's user groups) still apply.

## HTTPS on your network

Passkeys, and Focus Funnel's `Secure` cookies, work only on `localhost` or HTTPS. To use Focus Funnel from other devices, put an HTTPS reverse proxy in front of it. [Caddy](https://caddyserver.com) makes and renews the certificates.

This `Caddyfile` serves Focus Funnel and Pocket ID on two names. For names that only exist on your network, `tls internal` uses Caddy's own certificate authority, which each device must trust once. With a public domain, remove `tls internal` and Caddy gets certificates from Let's Encrypt.

```
focus.home.example {
	tls internal
	reverse_proxy localhost:3000
}

id.home.example {
	tls internal
	reverse_proxy localhost:1411
}
```

Then set in `.env`:

```sh
APP_BASE_URL=https://focus.home.example
OIDC_ISSUER=https://id.home.example
POCKET_ID_APP_URL=https://id.home.example
POCKET_ID_TRUST_PROXY=true
```

and change the Pocket ID client's callback URL to `https://focus.home.example/auth/callback` and its logout callback URL to `https://focus.home.example/`.

## Demo mode

Demo mode is for a public instance where strangers try the app. There is no login:

- Each visitor gets an anonymous user behind a random session cookie. Only a hash of the cookie is stored. One visitor cannot see another's conversations, even with the URL.
- A visitor's user and all their data are deleted after `DEMO_SESSION_TTL_HOURS` (24 by default), or at once when they select **End demo**.
- API keys are not stored on the server. The visitor's browser holds a key in an encrypted, HttpOnly cookie. It is forgotten after `DEMO_KEY_TTL_MINUTES` without use (30) or `DEMO_KEY_MAX_HOURS` after it was saved (4), whichever comes first. **Forget key** removes it at once.
- Before the first message, a notice says what is stored, when it is deleted, that the operator can read stored conversations, and what the chosen provider does with prompts.

Run it with the demo overlay, which sets `AUTH_MODE=demo` and keeps Postgres data in memory, so a restart deletes everything:

```sh
docker compose -f docker-compose.yml -f docker-compose.demo.yml up --build
```

The guards:

- Demo mode refuses to start when any `OIDC_*` or `FIREBASE_*` setting has a value. Leave them empty.
- The custom provider (a user-supplied base URL) is off, so visitors cannot point the server at internal addresses. Setting `ALLOW_CUSTOM_PROVIDER=true` stops the server from starting.
- Every response is marked `Cache-Control: no-store`.
- `DEMO_RATE_LIMIT` limits requests per minute (60), `DEMO_NEW_SESSIONS_PER_HOUR` limits new sessions per hour (5), and `DEMO_MAX_SESSIONS` limits live sessions (500). A visitor past a limit is told when to try again.

The rate limits are counted per client address only when `TRUSTED_PROXY=true`. Set it when Focus Funnel runs behind a reverse proxy that adds `X-Forwarded-For`; the last hop, which your proxy adds, is the client address. Without `TRUSTED_PROXY=true`, the server cannot tell visitors apart safely, so all requests share one limit for the whole instance. Never set it without a proxy in front: a visitor could then send their own `X-Forwarded-For` to dodge the limits.

The limits are kept in the frontend server's memory, so demo mode runs one frontend instance. Do not scale it out.

A public demo needs HTTPS for its cookies. Put it behind a reverse proxy such as Caddy, as in [HTTPS on your network](#https-on-your-network), and set `TRUSTED_PROXY=true`.
