// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { decideAction } from "@/lib/conversations";
import {
  actionEvent,
  delta,
  detail,
  done,
  errorResponse,
  fakeApi,
  json,
  loadout,
  openStream,
  storedMessage,
  streamOf,
  toolEvent,
  wireAction,
} from "@/test/fake-api";

import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const DECIDE = "POST /api/conversations/c1/actions/a1";

/** A conversation whose last answer is waiting on action a1. */
function waiting(action: Record<string, unknown> = {}) {
  return detail({
    messages: [
      storedMessage(0, "user", "add the dentist"),
      storedMessage(1, "assistant", null, {
        tool_calls: [
          {
            id: "t1",
            type: "function",
            function: { name: "calendar__create_event", arguments: "{}" },
          },
        ],
      }),
      storedMessage(2, "tool", "The action is shown to the user to approve.", {
        tool_call_id: "t1",
        details: { action_id: "a1" },
      }),
      storedMessage(3, "assistant", "It is waiting for your approval."),
    ],
    actions: [wireAction("a1", action)],
  });
}

function api(routes: Parameters<typeof fakeApi>[0] = {}, action: Record<string, unknown> = {}) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/conversations/c1": json(200, waiting(action)),
    ...routes,
  });
}

async function openChat() {
  render(<Chat conversationId="c1" />);
  return screen.findByRole("group", { name: "Action: calendar: Create event" });
}

function send(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

/** A response the test answers later, to see the card while it runs. */
function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((r) => {
    resolve = r;
  });
  return { handler: () => promise, resolve };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ActionCard", () => {
  it("shows the connector, the tool, and the arguments, nested values as JSON", async () => {
    api();
    const card = await openChat();

    expect(card).toHaveTextContent("calendar: Create event (create_event)");
    const list = card.querySelector("dl") as HTMLElement;
    const terms = within(list).getAllByRole("term").map((term) => term.textContent);
    expect(terms).toEqual(["summary", "start", "attendees"]);
    const values = within(list).getAllByRole("definition").map((value) => value.textContent);
    expect(values[0]).toBe("Dentist");
    expect(values[1]).toBe("2026-11-06T09:00");
    expect(values[2]).toBe(JSON.stringify(["sam@example.com"], null, 2));
    expect(within(card).getByRole("status")).toHaveTextContent("Waiting for your approval.");
    expect(within(card).getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Decline" })).toBeEnabled();
  });

  it("labels a stored call that asked for approval as asked, not used", async () => {
    api({}, { status: "expired" });
    await openChat();

    expect(screen.getByTestId("tool-indication")).toHaveTextContent(
      "Asked to use calendar: create_event",
    );
  });

  it("names the tool when it has no title", async () => {
    api({}, { title: null });
    render(<Chat conversationId="c1" />);

    expect(
      await screen.findByRole("group", { name: "Action: calendar: create_event" }),
    ).toHaveTextContent("calendar: create_event");
  });

  it("approves through the route, shows it running, then done with the result", async () => {
    const answer = deferred();
    const { calls } = api({ [DECIDE]: answer.handler });
    const card = await openChat();

    fireEvent.click(within(card).getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(within(card).getByRole("status")).toHaveTextContent("Running…"));
    expect(within(card).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")).toEqual({
      method: "POST",
      path: "/api/conversations/c1/actions/a1",
      body: { decision: "approve" },
    });

    answer.resolve(json(200, wireAction("a1", { status: "done", result: "Created: Dentist" })));

    await waitFor(() => expect(within(card).getByRole("status")).toHaveTextContent("Done."));
    expect(card).toHaveTextContent("Created: Dentist");
    expect(card).toHaveAttribute("data-status", "done");
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows an error the tool reported as the outcome", async () => {
    api({
      [DECIDE]: json(
        200,
        wireAction("a1", { status: "done", result: "no such calendar", error_code: "tool_error" }),
      ),
    });
    const card = await openChat();

    fireEvent.click(within(card).getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(within(card).getByRole("status")).toHaveTextContent(
        "Ran, and the tool reported an error:",
      ),
    );
    expect(card).toHaveTextContent("no such calendar");
  });

  it("declines through the route and shows that nothing was sent", async () => {
    const { calls } = api({ [DECIDE]: json(200, wireAction("a1", { status: "declined" })) });
    const card = await openChat();

    fireEvent.click(within(card).getByRole("button", { name: "Decline" }));

    await waitFor(() =>
      expect(within(card).getByRole("status")).toHaveTextContent("Declined. Nothing was sent."),
    );
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ decision: "decline" });
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows why a failed call did not run and lets the user approve it again", async () => {
    const { calls } = api({
      [DECIDE]: [
        json(
          200,
          wireAction("a1", {
            status: "failed",
            result: "The server could not be reached.",
            error_code: "connector_unreachable",
          }),
        ),
        json(200, wireAction("a1", { status: "done", result: "Created: Dentist" })),
      ],
    });
    const card = await openChat();

    fireEvent.click(within(card).getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(within(card).getByRole("status")).toHaveTextContent(
        "Did not run. The server could not be reached.",
      ),
    );
    expect(card).toHaveAttribute("data-status", "failed");

    fireEvent.click(within(card).getByRole("button", { name: "Approve again" }));

    await waitFor(() => expect(within(card).getByRole("status")).toHaveTextContent("Done."));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(2);
  });

  it("says an approval with no outcome may have run, and does not offer it again", async () => {
    api({
      [DECIDE]: json(
        200,
        wireAction("a1", {
          status: "unknown",
          result: "The server did not answer within 30 seconds.",
          error_code: "connector_unreachable",
        }),
      ),
    });
    const card = await openChat();

    fireEvent.click(within(card).getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(within(card).getByRole("status")).toHaveTextContent(
        "Sent, but it is not known whether it ran. Check before trying again. " +
          "The server did not answer within 30 seconds.",
      ),
    );
    expect(card).toHaveAttribute("data-status", "unknown");
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows that the action expired when the server answers action_expired", async () => {
    api({
      [DECIDE]: errorResponse(409, "action_expired", "This action expired."),
    });
    const card = await openChat();

    fireEvent.click(within(card).getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(within(card).getByRole("status")).toHaveTextContent(
        "Expired: the conversation moved on, so this did not run.",
      ),
    );
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps the card open and says why when the conversation is busy", async () => {
    api({
      [DECIDE]: errorResponse(409, "conversation_busy", "This conversation is still answering."),
    });
    const card = await openChat();

    fireEvent.click(within(card).getByRole("button", { name: "Approve" }));

    expect(await within(card).findByRole("alert")).toHaveTextContent(
      "This conversation is still answering.",
    );
    expect(within(card).getByRole("status")).toHaveTextContent("Waiting for your approval.");
    expect(within(card).getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("shows the card from the action event, and the same card after a reload", async () => {
    const stream = openStream();
    fakeApi({
      "GET /api/settings/models": json(200, loadout()),
      "GET /api/conversations/c1": json(200, detail({ messages: [] })),
      "POST /api/chat": () => stream.response,
    });
    const { unmount } = render(<Chat conversationId="c1" />);
    await screen.findByLabelText("Message");

    send("add the dentist");
    await stream.push(toolEvent("calendar__create_event", "start"));
    await stream.push(actionEvent("a1"));
    await stream.push(
      toolEvent("calendar__create_event", "end", "calendar: create_event is waiting for your approval"),
    );
    await stream.push(delta("It is waiting for your approval.") + done);
    await stream.close();

    const live = await screen.findByRole("group", { name: "Action: calendar: Create event" });
    const liveText = live.textContent;
    expect(screen.getByTestId("tool-indication")).toHaveTextContent(
      "calendar: create_event is waiting for your approval",
    );
    unmount();
    vi.unstubAllGlobals();

    api();
    const reloaded = await openChat();

    expect(reloaded.textContent).toBe(liveText);
    expect(reloaded).toHaveAttribute("data-status", "pending");
  });

  it("shows every state a reloaded conversation stored", async () => {
    for (const [status, text] of [
      ["done", "Done."],
      ["failed", "Did not run."],
      ["declined", "Declined. Nothing was sent."],
      ["expired", "Expired: the conversation moved on, so this did not run."],
      ["running", "Running…"],
      ["unknown", "Sent, but it is not known whether it ran."],
    ]) {
      api({}, { status, result: status === "done" ? "Created" : null });
      const { unmount } = render(<Chat conversationId="c1" />);
      const card = await screen.findByRole("group", { name: "Action: calendar: Create event" });
      expect(within(card).getByRole("status")).toHaveTextContent(text);
      unmount();
      vi.unstubAllGlobals();
    }
  });

  it("marks a waiting card expired once the next message's answer starts", async () => {
    api({
      "POST /api/chat": () => streamOf(delta("Sure."), done),
    });
    const card = await openChat();

    send("never mind");

    await screen.findByText("Sure.");
    expect(within(card).getByRole("status")).toHaveTextContent("Expired");
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
  });

  it("marks a waiting card expired when the next message is stored but refused", async () => {
    api({
      "POST /api/chat": () =>
        errorResponse(422, "too_many_tools", "Turn some connector tools off: the limit is 20.", {
          "X-Conversation-Id": "c1",
        }),
    });
    const card = await openChat();

    send("and now?");

    await screen.findByText("Turn some connector tools off: the limit is 20.");
    // The server stored the message and expired the card with it.
    expect(within(card).getByRole("status")).toHaveTextContent("Expired");
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps a waiting card open when the next message is refused before it is stored", async () => {
    api({
      "POST /api/chat": () =>
        errorResponse(409, "conversation_busy", "This conversation is still answering."),
    });
    const card = await openChat();

    send("and now?");

    await screen.findByText("This conversation is still answering.");
    expect(within(card).getByRole("status")).toHaveTextContent("Waiting for your approval.");
  });

  it("disables Approve and Decline while an answer arrives", async () => {
    const stream = openStream();
    api({ "POST /api/chat": () => stream.response });
    const card = await openChat();
    const approve = within(card).getByRole("button", { name: "Approve" });

    send("one more thing");
    await waitFor(() => expect(approve).toBeDisabled());
    await stream.close();
  });
});

describe("decideAction", () => {
  it("reads the action the route answers", async () => {
    fakeApi({ [DECIDE]: json(200, wireAction("a1", { status: "declined" })) });

    const action = await decideAction("c1", "a1", "decline");

    expect(action).toMatchObject({ id: "a1", status: "declined", connector: "calendar" });
  });
});
