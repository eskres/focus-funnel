> **Planning status:** Planned. Specs, design, and tasks are written. Depends on `conversation-agent` (the tool loop, landed) and `auth-modes` (demo mode).

## Why

What is useful to connect differs for each user: one wants a calendar, another a task list, a notes folder, or a work tool. The Model Context Protocol (MCP) is the common way for a model to use such services. Letting users add their own MCP servers, instead of shipping a fixed set, makes the app fit each person's work. It also brings real risk, because content from those services reaches the model and the model can act on it, so the change ships with limits.

## What Changes

- Add connectors: a user-added MCP server with a name, a server URL, optional header or bearer auth stored encrypted, and the list of its tools the user has switched on. Only remote servers reached by URL are supported.
- Give the tool loop a tool-provider interface. The built-in provider offers `search_thoughts` and `propose_thought`, and each connector is another provider. Tool names are prefixed with the connector name.
- Add a Connectors section to settings: pick from a small catalog or paste a URL, a Test that connects and lists the tools, and a switch and a read or write badge for each tool.
- Store which connectors are on with each conversation, chosen from a toggle beside the model dropdown. Connectors are off by default in a new conversation.
- Ask before any action that is not read-only, using the same confirmation card as a proposed thought. The user can set "always allow" for a single tool. A server's own read-only hint is only a hint.
- Treat tool results as untrusted data: label them as data for the model, cap their size, and never let a result trigger a write without a card.
- Count enabled tool definitions in the context meter and limit enabled tools per conversation (about 20 to start), because each definition costs tokens on every turn and weakens tool choice on small models.
- Report a connector that is down or slow as a tool error, and keep the chat going.
- Make it opt-in and controlled by the operator:
  - `MCP_ENABLED=false` by default. Demo mode forces it off.
  - `MCP_USER_CONNECTORS=false` by default. Connectors are then defined by the operator in configuration, and turning it on lets users add servers of their own.
  - A warning at the first add and in the docs: connectors let the model read from and act on external services, content from them can contain instructions aimed at the model, so add only servers you trust and review actions before approving them.
  - A user-supplied URL uses the same guard as a custom provider URL.
- Document a worked example for Google Calendar: the user runs their own Google Calendar MCP server with their own Google credentials, and the app connects to its URL. The app ships no Google credentials. Also provide a compose example that puts a local, command-based MCP server in its own container behind an HTTP address.

**Not in this change:** OAuth 2.1 sign-in to remote servers, pinning of tool descriptions, launching command-based servers inside the backend, MCP resources and prompts, and exposing Focus Funnel itself as an MCP server.

## Capabilities

### New Capabilities

- `mcp-connectors`: Adding, testing, and removing connectors, choosing tools and connectors per conversation, confirmation of actions, the operator switches, and the warning.

### Modified Capabilities

- `conversation-agent`: The model may use tools from connectors as well as the two built-in tools, inside the same bounded loop.
- `context-management`: The meter counts the tokens of enabled tool definitions.
- `conversations`: A conversation stores which connectors are on.

## Impact

- **Backend:** a `connectors` table with encrypted auth, a `conversation_connectors` link, an MCP client for remote servers, the tool-provider seam in the loop, the confirmation path, size limits and timeouts, and the two environment switches.
- **Frontend:** the Connectors settings section, the per-conversation toggle, the confirmation card for connector actions, and the tool token count in the meter.
- **Deployment:** a compose example for a command-based MCP server in a sidecar container.
- **Dependencies:** an MCP client library, likely the official Python SDK, to be checked when picked up.
- **Open questions:** resolved in `design.md` (decisions 1 and 9); the exact SDK version and annotation field names are confirmed by task 1.1.
