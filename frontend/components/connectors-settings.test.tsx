// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  connectorsListing,
  errorResponse,
  fakeApi,
  json,
  wireConnector,
  wireTool,
} from "@/test/fake-api";

import { ConnectorsSection, WARNING_TEXT } from "./connectors-settings";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const accepted = () => new Response(null, { status: 204 });

const CALENDAR_ENTRY = {
  name: "calendar",
  title: "Google Calendar",
  description: "Your Google Calendar events.",
  url: "http://gcal-mcp:8000/mcp",
  auth_kind: "none",
  auth_header: null,
  guide: "https://github.com/eskres/focus-funnel/blob/main/docs/connectors.md#google-calendar",
};

const operatorConnector = (tools: unknown[] = []) =>
  wireConnector("op1", "calendar", tools, {
    source: "operator",
    url: null,
    auth_kind: "bearer",
    auth_set: true,
    auth_last4: null,
  });

async function section() {
  return screen.findByRole("heading", { name: "Connectors" });
}

function connectorSection(name: string) {
  return screen.getByRole("region", { name });
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("ConnectorsSection: the warning", () => {
  it("shows the warning before the first add and keeps the form closed until it is accepted", async () => {
    const { calls } = fakeApi({
      "GET /api/connectors": json(200, connectorsListing([], { warning_accepted: false })),
      "POST /api/connectors/warning": accepted(),
    });
    render(<ConnectorsSection />);
    await section();

    fireEvent.click(screen.getByRole("button", { name: "Add connector" }));
    const dialog = screen.getByRole("dialog");
    for (const line of WARNING_TEXT) expect(within(dialog).getByText(line)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Add a connector" })).toBeNull();

    // Cancelling leaves the form closed and stores nothing.
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.queryByRole("form", { name: "Add a connector" })).toBeNull();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Add connector" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "I understand" }));

    expect(await screen.findByRole("form", { name: "Add a connector" })).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual([
      "/api/connectors/warning",
    ]);
  });

  it("does not show the warning again once accepted", async () => {
    const { calls } = fakeApi({
      "GET /api/connectors": json(200, connectorsListing([], { warning_accepted: true })),
    });
    render(<ConnectorsSection />);
    await section();

    fireEvent.click(screen.getByRole("button", { name: "Add connector" }));

    expect(screen.getByRole("form", { name: "Add a connector" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("asks for the warning before the first tool is switched on", async () => {
    const tool = wireTool("list_events", { enabled: false });
    const { calls } = fakeApi({
      "GET /api/connectors": json(
        200,
        connectorsListing([operatorConnector([tool])], {
          warning_accepted: false,
          user_connectors_allowed: false,
        }),
      ),
      "POST /api/connectors/warning": accepted(),
      "PATCH /api/connectors/op1/tools/list_events": json(
        200,
        operatorConnector([{ ...tool, enabled: true }]),
      ),
    });
    render(<ConnectorsSection />);
    await section();

    fireEvent.click(screen.getByRole("switch", { name: "Use calendar: list_events" }));
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "I understand" }));

    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "Use calendar: list_events" })).toBeChecked(),
    );
    expect(calls.filter((c) => c.method !== "GET").map((c) => [c.method, c.path, c.body])).toEqual([
      ["POST", "/api/connectors/warning", undefined],
      ["PATCH", "/api/connectors/op1/tools/list_events", { enabled: true }],
    ]);
  });
});

describe("ConnectorsSection: adding and editing", () => {
  it("fills the add form from the catalog and links to the guide", async () => {
    const saved = wireConnector("c1", "calendar", [], {
      url: CALENDAR_ENTRY.url,
      tools_listed_at: null,
    });
    const { calls } = fakeApi({
      "GET /api/connectors": json(200, connectorsListing([], { catalog: [CALENDAR_ENTRY] })),
      "POST /api/connectors": json(201, saved),
    });
    render(<ConnectorsSection />);
    await section();

    const catalog = screen.getByRole("list", { name: "Connector catalog" });
    expect(within(catalog).getByText("Your Google Calendar events.")).toBeInTheDocument();
    fireEvent.click(within(catalog).getByRole("button", { name: "Use Google Calendar" }));

    const form = screen.getByRole("form", { name: "Add a connector" });
    expect(within(form).getByLabelText("Name")).toHaveValue("calendar");
    expect(within(form).getByLabelText("Server URL")).toHaveValue("http://gcal-mcp:8000/mcp");
    expect(within(form).getByLabelText("Auth")).toHaveValue("none");
    expect(within(form).getByRole("link", { name: "Read how to set it up" })).toHaveAttribute(
      "href",
      CALENDAR_ENTRY.guide,
    );

    // The user can change the filled form before saving.
    fill("Name", "gcal");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("region", { name: "calendar" })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Add a connector" })).toBeNull();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "gcal",
      url: "http://gcal-mcp:8000/mcp",
      auth_kind: "none",
    });
  });

  it("shows only the last 4 characters of the auth value", async () => {
    const token = "secret-token-abcd-wxyz";
    const saved = wireConnector("c1", "calendar", [], {
      auth_kind: "bearer",
      auth_set: true,
      auth_last4: "wxyz",
    });
    const { calls } = fakeApi({
      "GET /api/connectors": json(200, connectorsListing([])),
      "POST /api/connectors": json(201, saved),
    });
    const { container } = render(<ConnectorsSection />);
    await section();

    fireEvent.click(screen.getByRole("button", { name: "Add connector" }));
    fill("Name", "calendar");
    fill("Server URL", "https://calendar.example.com/mcp");
    fireEvent.change(screen.getByLabelText("Auth"), { target: { value: "bearer" } });
    expect(screen.getByLabelText("Token")).toHaveAttribute("type", "password");
    fill("Token", token);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    const item = await screen.findByRole("region", { name: "calendar" });
    expect(within(item).getByText("Bearer token ending in wxyz.")).toBeInTheDocument();
    expect(container.textContent).not.toContain("secret-token");
    expect(container.querySelector("input[type=password]")).toBeNull();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "calendar",
      url: "https://calendar.example.com/mcp",
      auth_kind: "bearer",
      auth_value: token,
    });
  });

  it("edits a connector, sending only what changed and keeping the stored value", async () => {
    const connector = wireConnector("c1", "calendar", [], {
      auth_kind: "header",
      auth_header: "X-Api-Key",
      auth_set: true,
      auth_last4: "1234",
    });
    const { calls } = fakeApi({
      "GET /api/connectors": json(200, connectorsListing([connector])),
      "PATCH /api/connectors/c1": json(200, { ...connector, url: "https://new.example.com/mcp" }),
    });
    render(<ConnectorsSection />);
    await section();

    const item = connectorSection("calendar");
    expect(within(item).getByText("Header X-Api-Key, value ending in 1234.")).toBeInTheDocument();
    fireEvent.click(within(item).getByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Edit calendar" });
    expect(within(form).getByLabelText("Header value")).toHaveAttribute(
      "placeholder",
      "Leave empty to keep the one ending in 1234",
    );
    fireEvent.change(within(form).getByLabelText("Server URL"), {
      target: { value: "https://new.example.com/mcp" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(await within(item).findByText("https://new.example.com/mcp")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      url: "https://new.example.com/mcp",
    });
  });

  it("shows the server's message when the add is refused and keeps the form", async () => {
    fakeApi({
      "GET /api/connectors": json(200, connectorsListing([])),
      "POST /api/connectors": errorResponse(
        422,
        "validation_error",
        "url: must be an http or https URL",
      ),
    });
    render(<ConnectorsSection />);
    await section();

    fireEvent.click(screen.getByRole("button", { name: "Add connector" }));
    fill("Name", "files");
    fill("Server URL", "file:///etc/passwd");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("url: must be an http or https URL");
    expect(screen.getByLabelText("Server URL")).toHaveValue("file:///etc/passwd");
  });

  it("deletes a user connector after a second click", async () => {
    const { calls } = fakeApi({
      "GET /api/connectors": json(200, connectorsListing([wireConnector("c1", "calendar")])),
      "DELETE /api/connectors/c1": new Response(null, { status: 204 }),
    });
    render(<ConnectorsSection />);
    await section();

    const item = connectorSection("calendar");
    fireEvent.click(within(item).getByRole("button", { name: "Delete" }));
    expect(within(item).getByText(/turns it off in every conversation/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
    fireEvent.click(within(item).getByRole("button", { name: "Delete calendar" }));

    await waitFor(() => expect(screen.queryByRole("region", { name: "calendar" })).toBeNull());
    expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual([
      "/api/connectors/c1",
    ]);
  });
});

describe("ConnectorsSection: Test", () => {
  it("lists the tools a test finds, switched off", async () => {
    const tested = wireConnector("c1", "calendar", [
      wireTool("list_events", { enabled: false }),
      wireTool("create_event", {
        enabled: false,
        acts: true,
        read_only_hint: false,
        reads_allowed: false,
      }),
    ]);
    fakeApi({
      "GET /api/connectors": json(
        200,
        connectorsListing([wireConnector("c1", "calendar", [], { tools_listed_at: null })]),
      ),
      "POST /api/connectors/c1/test": json(200, tested),
    });
    render(<ConnectorsSection />);
    await section();

    const item = connectorSection("calendar");
    expect(within(item).getByText("Not tested yet. Test it to list its tools.")).toBeInTheDocument();
    fireEvent.click(within(item).getByRole("button", { name: "Test" }));

    expect(await within(item).findByText("The server answered with 2 tools.")).toBeInTheDocument();
    const list = within(item).getByRole("list", { name: "calendar tools" });
    for (const name of ["list_events", "create_event"]) {
      expect(within(list).getByRole("switch", { name: `Use calendar: ${name}` })).not.toBeChecked();
    }
    expect(within(list).getByLabelText("What calendar: list_events does")).toHaveValue("reads");
    expect(within(list).getByLabelText("What calendar: create_event does")).toHaveValue("acts");
  });

  it.each([
    ["connector_unreachable", "The server could not be reached."],
    ["connector_auth_failed", "The server refused the auth."],
    ["connector_protocol_error", "The server did not answer as an MCP server."],
  ])("says in plain words why a test failed (%s)", async (code, message) => {
    const connector = wireConnector("c1", "calendar", [wireTool("list_events")]);
    fakeApi({
      "GET /api/connectors": json(200, connectorsListing([connector])),
      "POST /api/connectors/c1/test": errorResponse(502, code, message),
    });
    render(<ConnectorsSection />);
    await section();

    const item = connectorSection("calendar");
    fireEvent.click(within(item).getByRole("button", { name: "Test" }));

    expect(await within(item).findByRole("alert")).toHaveTextContent(message);
    // The stored tool list stays as it was.
    expect(within(item).getByRole("switch", { name: "Use calendar: list_events" })).toBeChecked();
  });
});

describe("ConnectorsSection: operator connectors", () => {
  it("offers no edit, delete, or add when users may not add connectors", async () => {
    fakeApi({
      "GET /api/connectors": json(
        200,
        connectorsListing([operatorConnector([wireTool("list_events")])], {
          user_connectors_allowed: false,
          catalog: [],
        }),
      ),
    });
    render(<ConnectorsSection />);
    await section();

    const item = connectorSection("calendar");
    expect(within(item).getByText("Set up by the operator")).toBeInTheDocument();
    expect(within(item).getByText("Bearer token, set by the operator.")).toBeInTheDocument();
    expect(within(item).getByRole("button", { name: "Test" })).toBeInTheDocument();
    expect(within(item).queryByRole("button", { name: "Edit" })).toBeNull();
    expect(within(item).queryByRole("button", { name: /Delete/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add connector" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Connector catalog" })).toBeNull();
    // Its tools can still be switched.
    expect(within(item).getByRole("switch", { name: "Use calendar: list_events" })).toBeEnabled();
  });

  it("lists operator connectors beside the user's own, with edit and delete only on the user's", async () => {
    fakeApi({
      "GET /api/connectors": json(
        200,
        connectorsListing([operatorConnector(), wireConnector("c2", "notes")]),
      ),
    });
    render(<ConnectorsSection />);
    await section();

    expect(within(connectorSection("calendar")).queryByRole("button", { name: "Edit" })).toBeNull();
    expect(within(connectorSection("notes")).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add connector" })).toBeInTheDocument();
  });
});

describe("ConnectorsSection: tools", () => {
  const ACTS_TOOL = wireTool("create_event", {
    read_only_hint: false,
    acts: true,
    reads_allowed: false,
    enabled: false,
  });

  it("never offers reads for a tool the server marks as acting", async () => {
    fakeApi({
      "GET /api/connectors": json(200, connectorsListing([wireConnector("c1", "calendar", [ACTS_TOOL])])),
    });
    render(<ConnectorsSection />);
    await section();

    const select = screen.getByLabelText("What calendar: create_event does");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Acts"]);
    expect(select).toHaveValue("acts");
    expect(select).toBeDisabled();
  });

  it("lets a reads tool move to acts, and back", async () => {
    const tool = wireTool("list_events");
    const { calls } = fakeApi({
      "GET /api/connectors": json(200, connectorsListing([wireConnector("c1", "calendar", [tool])])),
      "PATCH /api/connectors/c1/tools/list_events": [
        json(200, wireConnector("c1", "calendar", [{ ...tool, acts: true }])),
        json(200, wireConnector("c1", "calendar", [tool])),
      ],
    });
    render(<ConnectorsSection />);
    await section();

    const select = () => screen.getByLabelText("What calendar: list_events does");
    expect(within(select()).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Reads",
      "Acts",
    ]);
    fireEvent.change(select(), { target: { value: "acts" } });
    await waitFor(() => expect(select()).toHaveValue("acts"));
    expect(screen.getByLabelText("Always allow calendar: list_events")).toBeInTheDocument();
    fireEvent.change(select(), { target: { value: "reads" } });
    await waitFor(() => expect(select()).toHaveValue("reads"));
    expect(screen.queryByLabelText("Always allow calendar: list_events")).toBeNull();

    expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([
      { acts: true },
      { acts: false },
    ]);
  });

  it("does not let an unavailable tool be switched on", async () => {
    const longName = "a_tool_name_long_enough_to_push_past_the_limit_of_64";
    const tool = wireTool(longName, { available: false, enabled: false });
    const { calls } = fakeApi({
      "GET /api/connectors": json(200, connectorsListing([wireConnector("c1", "calendar", [tool])])),
    });
    render(<ConnectorsSection />);
    await section();

    const toggle = screen.getByRole("switch", { name: `Use calendar: ${longName}` });
    expect(toggle).toBeDisabled();
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(screen.getByText(/is not a valid tool name/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
  });

  it("switches a tool on and off", async () => {
    const tool = wireTool("list_events", { enabled: false });
    const { calls } = fakeApi({
      "GET /api/connectors": json(200, connectorsListing([wireConnector("c1", "calendar", [tool])])),
      "PATCH /api/connectors/c1/tools/list_events": [
        json(200, wireConnector("c1", "calendar", [{ ...tool, enabled: true }])),
        json(200, wireConnector("c1", "calendar", [tool])),
      ],
    });
    render(<ConnectorsSection />);
    await section();

    const toggle = () => screen.getByRole("switch", { name: "Use calendar: list_events" });
    fireEvent.click(toggle());
    await waitFor(() => expect(toggle()).toBeChecked());
    fireEvent.click(toggle());
    await waitFor(() => expect(toggle()).not.toBeChecked());
    expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([
      { enabled: true },
      { enabled: false },
    ]);
  });

  it("asks before setting always allow, and does nothing on cancel", async () => {
    const { calls } = fakeApi({
      "GET /api/connectors": json(200, connectorsListing([wireConnector("c1", "calendar", [ACTS_TOOL])])),
      "PATCH /api/connectors/c1/tools/create_event": [
        json(200, wireConnector("c1", "calendar", [{ ...ACTS_TOOL, always_allow: true }])),
        json(200, wireConnector("c1", "calendar", [ACTS_TOOL])),
      ],
    });
    render(<ConnectorsSection />);
    await section();

    const box = () => screen.getByLabelText("Always allow calendar: create_event");
    fireEvent.click(box());
    let dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Always allow calendar: create_event?")).toBeInTheDocument();
    expect(within(dialog).getByText(/without asking you first/)).toBeInTheDocument();
    expect(box()).not.toBeChecked();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);

    fireEvent.click(box());
    dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Always allow" }));
    await waitFor(() => expect(box()).toBeChecked());

    // Turning it off needs no confirmation.
    fireEvent.click(box());
    await waitFor(() => expect(box()).not.toBeChecked());
    expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([
      { always_allow: true },
      { always_allow: false },
    ]);
  });

  it("shows the server's message when a tool change is refused", async () => {
    const tool = wireTool("list_events", { enabled: false });
    fakeApi({
      "GET /api/connectors": json(200, connectorsListing([wireConnector("c1", "calendar", [tool])])),
      "PATCH /api/connectors/c1/tools/list_events": errorResponse(
        422,
        "validation_error",
        "enabled: this tool can't be switched on",
      ),
    });
    render(<ConnectorsSection />);
    await section();

    fireEvent.click(screen.getByRole("switch", { name: "Use calendar: list_events" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("enabled: this tool can't be switched on");
    expect(screen.getByRole("switch", { name: "Use calendar: list_events" })).not.toBeChecked();
  });
});

describe("ConnectorsSection: connectors off", () => {
  it("renders nothing when the server answers 404", async () => {
    const { calls } = fakeApi({
      "GET /api/connectors": errorResponse(404, "not_found", "Not found."),
    });
    const { container } = render(<ConnectorsSection />);

    await waitFor(() => expect(calls).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container).toBeEmptyDOMElement();
  });

  it("says when the connectors could not be loaded", async () => {
    fakeApi({ "GET /api/connectors": errorResponse(500, "internal_error", "Boom.") });
    render(<ConnectorsSection />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The connectors could not be loaded.");
    expect(screen.getByRole("heading", { name: "Connectors" })).toBeInTheDocument();
  });
});
