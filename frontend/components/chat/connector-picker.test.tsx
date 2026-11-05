// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  connectorsListing,
  detail,
  errorResponse,
  fakeApi,
  json,
  loadout,
  loadoutEntry,
  storedMessage,
  wireConnector,
  wireTool,
} from "@/test/fake-api";

import { Chat } from "./chat";
import { ContextMeter } from "./context-meter";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app/c1",
}));

const NANO = "vendor/nano";
const models = loadout([loadoutEntry(NANO, { is_default: true })]);

const calendar = wireConnector("k1", "calendar", [
  wireTool("list_events"),
  wireTool("find_free_time"),
  // Not counted: switched off, or not a valid tool name.
  wireTool("create_event", { enabled: false, acts: true }),
  wireTool("bad.name", { available: false, enabled: false }),
]);
const work = wireConnector("k2", "work", [wireTool("search"), wireTool("read"), wireTool("list")]);
const empty = wireConnector("k3", "notes", [wireTool("find", { enabled: false })]);

function conversation(extra: Record<string, unknown> = {}) {
  return detail({
    id: "c1",
    title: "Rent",
    model: NANO,
    messages: [storedMessage(0, "user", "about rent"), storedMessage(1, "assistant", "Tell me more.")],
    context: { tokens: 1000, estimated: false, context_length: 131072, tool_tokens: 600 },
    connectors: [],
    ...extra,
  });
}

async function openPicker() {
  fireEvent.click(await screen.findByRole("button", { name: /^Connectors/ }));
  return screen.findByRole("menu");
}

function figure() {
  return screen.getByTestId("context-figure").textContent;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/app/c1");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("ConnectorPicker in the chat", () => {
  it("lists the user's connectors with the tools on against the limit", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, models),
      "GET /api/connectors": json(200, connectorsListing([calendar, work, empty])),
      "GET /api/conversations/c1": json(
        200,
        conversation({ connectors: [{ id: "k1", name: "calendar" }] }),
      ),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Tell me more.");

    const menu = await openPicker();

    expect(within(menu).getByTestId("connector-tool-count")).toHaveTextContent("2 of 20 tools");
    const items = within(menu).getAllByRole("menuitemcheckbox");
    expect(items.map((item) => item.textContent)).toEqual([
      "calendar2 tools",
      "work3 tools",
      "notesNo tools switched on in settings",
    ]);
    expect(items[0]).toHaveAttribute("aria-checked", "true");
    expect(items[1]).toHaveAttribute("aria-checked", "false");
    expect(items[1]).not.toHaveAttribute("aria-disabled", "true");
    // A connector with no switched-on tools is listed but cannot be turned on.
    expect(items[2]).toHaveAttribute("aria-disabled", "true");
  });

  it("is hidden when connectors are off on the server", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, models),
      "GET /api/connectors": errorResponse(404, "not_found", "Not found."),
      "GET /api/conversations/c1": json(200, conversation()),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Tell me more.");
    await screen.findByRole("option", { name: NANO });

    expect(screen.queryByRole("button", { name: /^Connectors/ })).not.toBeInTheDocument();
  });

  it("turns a connector on and marks the meter as an estimate with the new tools figure", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, models),
      "GET /api/connectors": json(200, connectorsListing([calendar, work])),
      "GET /api/conversations/c1": json(200, conversation()),
      "PUT /api/conversations/c1/connectors": json(
        200,
        conversation({
          last_prompt_tokens: null,
          context: { tokens: 1300, estimated: true, context_length: 131072, tool_tokens: 900 },
          connectors: [{ id: "k1", name: "calendar" }],
        }),
      ),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Tell me more.");
    expect(figure()).toBe("1k of 131.1k tokens");
    expect(screen.getByTestId("context-tools")).toHaveTextContent("tools: 600");

    const menu = await openPicker();
    fireEvent.click(within(menu).getByRole("menuitemcheckbox", { name: /calendar/ }));

    await waitFor(() => expect(figure()).toBe("About 1.3k of 131.1k tokens (estimate)"));
    expect(screen.getByTestId("context-tools")).toHaveTextContent("tools: 900");
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ connector_ids: ["k1"] });
    expect(screen.getByRole("button", { name: /^Connectors/ })).toHaveTextContent("Connectors (1)");
    expect(screen.getByRole("button", { name: /^Connectors/ })).toHaveAccessibleName(
      "Connectors: 1 on, 2 of 20 tools",
    );
  });

  it("turns a connector off with the rest of the set", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, models),
      "GET /api/connectors": json(200, connectorsListing([calendar, work])),
      "GET /api/conversations/c1": json(
        200,
        conversation({
          connectors: [
            { id: "k1", name: "calendar" },
            { id: "k2", name: "work" },
          ],
        }),
      ),
      "PUT /api/conversations/c1/connectors": json(
        200,
        conversation({ connectors: [{ id: "k2", name: "work" }] }),
      ),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Tell me more.");

    const menu = await openPicker();
    fireEvent.click(within(menu).getByRole("menuitemcheckbox", { name: /calendar/ }));

    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ connector_ids: ["k2"] }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Connectors/ })).toHaveAccessibleName(
        "Connectors: 1 on, 3 of 20 tools",
      ),
    );
  });

  it("shows the too_many_tools message and keeps the connector off", async () => {
    const message =
      "A conversation can have at most 20 connector tools switched on. Turn a connector off " +
      "here, or switch some of its tools off in settings.";
    fakeApi({
      "GET /api/settings/models": json(200, models),
      "GET /api/connectors": json(200, connectorsListing([calendar, work])),
      "GET /api/conversations/c1": json(
        200,
        conversation({ connectors: [{ id: "k1", name: "calendar" }] }),
      ),
      "PUT /api/conversations/c1/connectors": errorResponse(422, "too_many_tools", message),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Tell me more.");

    const menu = await openPicker();
    fireEvent.click(within(menu).getByRole("menuitemcheckbox", { name: /work/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: /^Connectors/ })).toHaveAccessibleName(
      "Connectors: 1 on, 2 of 20 tools",
    );
    expect(figure()).toBe("1k of 131.1k tokens");
  });

  it("cannot change connectors before a new conversation exists", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, models),
      "GET /api/connectors": json(200, connectorsListing([calendar])),
    });
    window.history.replaceState(null, "", "/app");
    render(<Chat />);

    const menu = await openPicker();

    expect(within(menu).getByText(/Send a message first/)).toBeInTheDocument();
    expect(within(menu).getByRole("menuitemcheckbox", { name: /calendar/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});

describe("ContextMeter", () => {
  it("shows the tools figure in its tooltip", () => {
    render(
      <ContextMeter
        meter={{ tokens: 5000, estimated: false, contextLength: 131072, toolTokens: 1234 }}
      />,
    );

    expect(screen.getByTitle("tools: 1.2k")).toBeInTheDocument();
    expect(screen.getByTestId("context-tools")).toHaveTextContent("tools: 1.2k");
    expect(figure()).toBe("5k of 131.1k tokens");
  });

  it("shows no tools figure when there is none", () => {
    render(<ContextMeter meter={{ tokens: 5000, estimated: true, contextLength: null }} />);

    expect(screen.queryByTestId("context-tools")).not.toBeInTheDocument();
  });
});
