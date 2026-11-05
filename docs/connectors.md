# Connectors

Connectors let the chat model use tools from [MCP](https://modelcontextprotocol.io) servers, such as reading a calendar and adding events to it. Each connector is one remote MCP server, reached by URL over Streamable HTTP. The app ships no server and no credentials for any service: you run the server, or pick one you trust.

Connectors are off unless you turn them on.

## The two switches

Both go in `.env`, and both are off by default.

| Setting | What it does |
|---|---|
| `MCP_ENABLED=true` | Turns connectors on. The operator's connectors from the configuration file are offered to every user, Settings gets a **Connectors** section, and the chat gets a connector menu beside the model dropdown. While it is off, the connector routes answer `404 not_found`, the configuration file is not read, and nothing about connectors shows. |
| `MCP_USER_CONNECTORS=true` | Also lets each user add servers of their own, by URL. It has no effect while `MCP_ENABLED` is off. Read [what it exposes](#what-mcp_user_connectorstrue-exposes) before you turn it on. |

Demo mode turns connectors off. It refuses to start when `MCP_ENABLED=true` is set, and the message names the setting.

## Operator connectors

The operator's connectors live in `backend/app/connectors.yaml`, or in the file `MCP_CONNECTORS_PATH` names. The shipped file has none. The file is read when the backend starts, and only when `MCP_ENABLED=true`. A file that is not valid stops the backend, with a message naming the connector and the field.

```yaml
connectors:
  - name: calendar                     # the prefix of its tool names
    url: http://gcal-mcp:8000/mcp      # the server's Streamable HTTP endpoint
    auth: {kind: bearer, env: GCAL_MCP_TOKEN}   # optional
    tools: [list-events, create-event]          # optional; default every tool
    read_only: [list-events]                    # optional
```

- **`name`:** a lowercase letter, then lowercase letters, digits, or underscores, at most 24 characters. The model sees each tool as `<name>__<tool>`, for example `calendar__list-events`. `search_thoughts` and `propose_thought` are taken.
- **`url`:** an `http` or `https` address. It can be a compose service or a private address: the operator chose it.
- **`auth`:** optional. `{kind: bearer, env: VAR}` sends `Authorization: Bearer <value of VAR>`. `{kind: header, header: X-Api-Key, env: VAR}` sends that header. The variable must be set when the backend starts. Its value is read from the environment for each call and is never stored in the database or shown to users.
- **`tools`:** the server tools to offer. Tools the server lists that are not named here are not shown.
- **`read_only`:** tools that only read, so they run without asking the user. The app trusts this list over the server's own hints. Each one must be in `tools` when `tools` is given.

Every user sees the operator's connectors in Settings and can test them and switch their tools on and off. No user can change or remove them. If you remove a connector from the file and restart, it disappears from every conversation.

The same file holds the `catalog`: known servers offered in the add form when users may add their own. Picking one fills in the form. The shipped catalog has the [Google Calendar](#google-calendar) server.

An operator connector is shared. Everyone who uses the app reaches the same server, with the same credentials. For a server that holds one person's data, such as a calendar, that fits an instance with one user. On a shared instance, each person should run their own server and add it as a user connector.

## User connectors

With `MCP_USER_CONNECTORS=true`, a user adds a connector in **Settings → Connectors**: a name, the server's URL, and optional auth (a bearer token, or one header name and value).

- The URL must be `http` or `https`, with no user name or password in it.
- The name follows the rules above. It must be unique for the user and must not be the name of an operator connector.
- The auth value is stored encrypted with `KEY_ENCRYPTION_KEY`, bound to the user and the connector. It is never sent back to the browser or written to the logs. Settings shows only its last 4 characters.
- Only the owner can see, change, or remove a connector. Removing one turns it off in every conversation, and deleting an account deletes its connectors.

## The warning

Before a user adds their first connector, or switches on their first tool, Settings shows this warning. They accept it once.

> Connectors let the model read from and act on outside services, such as your calendar.
>
> What those services send back can contain instructions aimed at the model, written by anyone who can put text there.
>
> Add only servers you trust, and check each action before you approve it.

The second point matters most. A calendar invitation, an email, or a web page can hold text written to make the model do something. The app marks every tool result as data and tells the model not to follow instructions inside it, but a model can still be fooled. The approval card is the safeguard: nothing that changes anything runs without the user's yes.

## What `MCP_USER_CONNECTORS=true` exposes

Turning it on lets any user make the backend send requests to an address of their choice:

- **The backend's network.** The URL check allows any host, including private addresses, compose service names, and cloud metadata addresses such as `169.254.169.254`. The backend sends MCP requests there, and Test shows whether the address answered as an MCP server. Do not turn it on where the backend can reach services that must stay private, unless a firewall or an egress proxy limits what it can reach. The same applies to `ALLOW_CUSTOM_PROVIDER`.
- **Conversation content.** A user's server receives the arguments of every tool call the model makes to it, which can include anything from that user's conversation.
- **Tool descriptions.** A server's tool names and descriptions go into the model's context in that user's conversations. They can hold instructions aimed at the model, like any tool result.

User connectors affect only the user who added them. One user's connectors never appear in another user's chat.

## Using connectors

1. In **Settings → Connectors**, press **Test** on a connector. The backend connects, lists the server's tools, and stores the list. Tools are listed only on Test, never during a chat, so test again after the server changes.
2. Switch on the tools the model may use. Each tool is marked **Reads** or **Acts**.
3. In a chat, send a message, then open the connector menu beside the model dropdown and tick the connectors this conversation may use. A new conversation has none on. The change applies from the next message.

The chat shows each tool the model uses as `connector: tool` under the answer, for example `calendar: list-events`.

### Reads and acts

A tool **reads** when the operator lists it in `read_only` or the server marks it read-only. Every other tool **acts**. A user can move a read tool to acts, but never an act tool to reads.

- A read runs at once, and the model sees its result.
- An act never runs straight away. The answer shows a card with the connector, the tool, and the arguments the model chose, and the model is told the action is waiting. **Approve** runs it once; **Decline** drops it. Either way the model learns the outcome in the next turn.
- A card left waiting expires when the user sends the next message, and the action does not run.
- If an approved action fails, for example because the server is down, the card says why and offers **Approve again**.

### Always allow

In Settings, an act tool can be set to **Always allow**, after a confirmation. The model then runs it without a card. One exception stays: once a turn has read anything from a connector, every act in the rest of that turn shows a card, even an always-allowed one. Text read from a service could be what is asking for the action.

## Limits and timeouts

These are in `backend/app/chat/chat.yaml`, under `connectors`. Users cannot change them.

| Setting | Default | What it limits |
|---|---|---|
| `max_tools` | 20 | Switched-on tools across one conversation's connectors. Turning on a connector that goes past it is refused with `too_many_tools`. The two built-in tools are not counted. |
| `tool_rounds` | 5 | Model calls in one turn while a connector is on, used instead of the chat's `tool_rounds`. |
| `connect_seconds` | 10 | Connecting to a server and starting its session. |
| `call_seconds` | 30 | Waiting for one tool call. A call that times out is not retried. |
| `result_max_chars` | 8000 | A tool result is cut to this many characters before the model sees it. |

A turn can take a while in the worst case: up to `tool_rounds` model calls, each of which can call several tools, each allowed `call_seconds`, plus `connect_seconds` once for each connector it uses. Lower `call_seconds` and `tool_rounds` to shorten it.

Each tool definition costs context on every turn. The context meter counts them: its tooltip shows the tool tokens. When the context is full, the message suggests turning some connectors off.

A server that cannot be reached, refuses the auth, does not answer in time, or does not answer as an MCP server gives the model a tool error, and the chat shows that tool in red. The answer still finishes. The backend connects at most once per turn, when the model first calls one of the connector's tools.

## Google Calendar

This example runs [`@cocal/google-calendar-mcp`](https://github.com/nspady/google-calendar-mcp) 2.7.0 in a container next to the app, behind the [`supergateway`](https://github.com/supercorp-ai/supergateway) 4.2.0 bridge, which serves it as Streamable HTTP. The server uses your own Google OAuth client, so your calendar data goes only between your machine and Google. `docker-compose.mcp.yml` adds the container as the `gcal-mcp` service, with no host port, and gives the backend an operator connector named `calendar` that points at it (`mcp/google-calendar/connectors.yaml`). The connector offers every tool the server has except `manage-accounts`, which would start a Google sign-in from inside a chat.

The connector is an operator connector, so every user of the instance reaches this one calendar. Use it on an instance only you use.

### 1. Create a Google OAuth client

1. In the [Google Cloud console](https://console.cloud.google.com), create a project, or pick one.
2. Enable the [Google Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com) for it.
3. Under **Google Auth Platform**, set up the consent screen with the **External** audience, and add your Google address as a test user under **Audience**.
4. Under **Clients**, create a client of type **Desktop app**, and download its JSON file.
5. Save the file as `.data/gcal-mcp/gcp-oauth.keys.json` in your checkout:

   ```sh
   mkdir -p .data/gcal-mcp
   cp ~/Downloads/client_secret_*.json .data/gcal-mcp/gcp-oauth.keys.json
   ```

Compose stops with an error when this file is missing.

While the app is in testing, Google lets its sign-ins last 7 days. After that, the calendar tools report that the tokens are not valid; repeat step 2 below.

### 2. Sign in to Google once

The server keeps its Google tokens in the `gcal-mcp-tokens` volume. Write them with the server's `auth` command, with its sign-in page on port 3500 of your machine:

```sh
docker compose -f docker-compose.yml -f docker-compose.mcp.yml run --rm --build -p 3500:3500 gcal-mcp google-calendar-mcp auth
```

Open http://localhost:3500 in your browser (the server says it opened one, but it cannot from inside the container), sign in with the Google account you added as a test user, and allow calendar access. The command ends when the tokens are saved.

### 3. Start the app with the overlay

Set up the app as in the README first, including login and a chat model that can call tools. Then start everything with the overlay:

```sh
docker compose -f docker-compose.yml -f docker-compose.mcp.yml up --build
```

The overlay sets `MCP_ENABLED=true` for the backend. If you use the Pocket ID overlay as well, add `-f docker-compose.pocket-id.yml` after the other two files.

### 4. Turn it on in the app

1. In **Settings → Connectors**, accept the warning when it shows, then press **Test** on `calendar`. It lists the server's tools.
2. Switch on the tools you want, for example `list-events`, `get-current-time`, and `create-event`. The read tools are marked Reads; `create-event`, `update-event`, `delete-event`, and the others that change your calendar are marked Acts.
3. Start a chat and send a message. Then open the connector menu beside the model dropdown and tick `calendar`.
4. Ask "What is on my calendar this week?" The answer lists your events and shows `calendar: list-events` under it.
5. Ask it to add an event. The answer shows a card with the event's details. Nothing is created until you press **Approve**.

### Without the overlay

To run the same server elsewhere, build `mcp/google-calendar/Dockerfile`, mount your OAuth client at `/config/gcp-oauth.keys.json` and a writable volume at `/tokens`, and point a connector at `http://<host>:8000/mcp`. With `MCP_USER_CONNECTORS=true`, users can pick **Google Calendar** from the catalog, which fills in `http://gcal-mcp:8000/mcp`; change the URL to wherever their server runs. Keep the server off the public internet: anyone who reaches it can read and change the calendar.
