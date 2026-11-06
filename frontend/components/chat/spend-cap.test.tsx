// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { browserTimeZone } from "@/lib/time-zone";
import {
  delta,
  detail,
  done,
  errorEvent,
  errorResponse,
  fakeApi,
  json,
  loadout,
  loadoutEntry,
  proposalEvent,
  source,
  storedMessage,
  streamOf,
  toolEvent,
  wireProposal,
  type WirePart,
} from "@/test/fake-api";

import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const NANO = "vendor/nano";
const settings = loadout([loadoutEntry(NANO, { is_default: true })]);
const REFUSED =
  "Your monthly spend cap of $5.00 is reached (this month so far: $5.12, estimated). Raise or remove it in Settings to keep chatting. It resets on 1 December (UTC).";
const CROSSED = "Your monthly spend cap of $5.00 is reached (this month so far: $5.01, estimated).";
const STORED =
  "Your monthly spend cap was reached during this answer. Raise or remove it in Settings to keep chatting.";
const OAT = source("t1", "Oat milk", "2026-08-02T09:00:00+00:00", ["groceries"]);
const EGGS: WirePart = { title: "Eggs", summary: "Buy eggs.", tags: ["groceries"], category: "task" };
const PROMPT = "what about milk?";

function send(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

function chatBodies(calls: { method: string; path: string; body: unknown }[]) {
  return calls.filter((c) => c.path === "/api/chat").map((c) => c.body as Record<string, unknown>);
}

function conversationList() {
  return screen.getByRole("list", { name: "Conversation" });
}

/** The cap alert, checked for its title, the given message, and the usage settings link. */
async function capAlert(message: string) {
  const alert = await screen.findByRole("alert");
  expect(within(alert).getByText("Monthly spend cap reached")).toBeInTheDocument();
  expect(within(alert).getByText(message)).toBeInTheDocument();
  expect(within(alert).getByRole("link", { name: "Go to usage settings" })).toHaveAttribute(
    "href",
    "/settings#usage",
  );
  return alert;
}

/** A turn that searched and proposed, then ended at the cap before its next round. */
const crossing = () =>
  streamOf(
    toolEvent("search_thoughts", "start"),
    toolEvent("search_thoughts", "end", "Searched your thoughts", [OAT]),
    toolEvent("propose_thought", "start"),
    proposalEvent("p1", [EGGS]),
    toolEvent("propose_thought", "end", "Proposed a thought to file"),
    errorEvent("spend_cap_reached", CROSSED),
  );

/** The same turn as stored: the tool-call message carries the cap's code. */
const storedCrossing = () => [
  storedMessage(0, "user", PROMPT),
  storedMessage(1, "assistant", null, {
    error_code: "spend_cap_reached",
    tool_calls: [
      { id: "a", type: "function", function: { name: "search_thoughts", arguments: "{}" } },
      { id: "b", type: "function", function: { name: "propose_thought", arguments: "{}" } },
    ],
  }),
  storedMessage(2, "tool", "1 match", {
    tool_call_id: "a",
    details: { sources: [OAT], summary: "Searched your thoughts" },
  }),
  storedMessage(3, "tool", "shown", {
    tool_call_id: "b",
    details: { proposal_id: "p1", summary: "Proposed a thought to file" },
  }),
];

function expectKeptTurn() {
  const tools = screen.getAllByTestId("tool-indication").map((t) => t.textContent);
  expect(tools.slice(0, 2)).toEqual(["Searched your thoughts", "Proposed a thought to file"]);
  const sources = screen.getAllByRole("region", { name: "Sources" })[0];
  expect(within(sources).getByRole("link", { name: "Oat milk" })).toBeInTheDocument();
  const card = screen.getByRole("group", { name: "Thought to file: Eggs" });
  expect(within(card).getByRole("button", { name: "Confirm" })).toBeEnabled();
}

beforeEach(() => {
  window.history.replaceState(null, "", "/app");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("the spend cap in the chat", () => {
  it("shows a refused send with the backend's message and a link to the usage settings", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, settings),
      "POST /api/chat": () => errorResponse(409, "spend_cap_reached", REFUSED),
    });
    render(<Chat />);

    send("hello");

    await capAlert(REFUSED);
    expect(within(conversationList()).getByText("hello")).toBeInTheDocument();
    expect(screen.queryByTestId("tool-indication")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toBeEnabled();
  });

  it("keeps the search and its sources when the stream ends at the cap", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, detail()),
      "POST /api/chat": () =>
        streamOf(
          toolEvent("search_thoughts", "start"),
          toolEvent("search_thoughts", "end", "Searched your thoughts", [OAT]),
          errorEvent("spend_cap_reached", CROSSED),
        ),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByLabelText("Message");

    send(PROMPT);

    await capAlert(CROSSED);
    expect(screen.getByTestId("tool-indication")).toHaveTextContent("Searched your thoughts");
    const sources = screen.getByRole("region", { name: "Sources" });
    expect(within(sources).getByRole("link", { name: "Oat milk" })).toBeInTheDocument();
  });

  it("keeps the proposal card when the stream ends at the cap", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, detail()),
      "POST /api/chat": () =>
        streamOf(proposalEvent("p1", [EGGS]), errorEvent("spend_cap_reached", CROSSED)),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByLabelText("Message");

    send(PROMPT);

    await capAlert(CROSSED);
    expect(screen.getByRole("group", { name: "Thought to file: Eggs" })).toBeInTheDocument();
  });

  it("says the cap was reached after a reload, under the kept tools, with a confirmable card", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(
        200,
        detail({ messages: storedCrossing(), proposals: [wireProposal("p1", [EGGS], 3)] }),
      ),
    });
    render(<Chat conversationId="c1" />);

    const alert = await capAlert(STORED);
    expect(within(alert).getByText(STORED).textContent).toBe(STORED);
    expectKeptTurn();
    // The alert comes after the kept tools in the answer.
    const tools = screen.getAllByTestId("tool-indication");
    expect(tools.at(-1)!.compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("sends a refused first message again to the conversation it was stored in, and shows it once", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, settings),
      "POST /api/chat": [
        () => errorResponse(409, "spend_cap_reached", REFUSED, { "X-Conversation-Id": "c1" }),
        () => streamOf(delta("Hi there."), done),
      ],
    });
    render(<Chat />);

    send("hello");
    await capAlert(REFUSED);
    expect(window.location.pathname).toBe("/app/c1");

    // The user raised the cap in the settings, then sends the same text again.
    send("hello");

    expect(await screen.findByText("Hi there.")).toBeInTheDocument();
    expect(chatBodies(calls)[1]).toEqual({
      message: "hello",
      time_zone: browserTimeZone(),
      conversation_id: "c1",
    });
    expect(within(conversationList()).getAllByText("hello")).toHaveLength(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("sends the same prompt as a new message after an answer ended at the cap, keeping that answer", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, detail()),
      "POST /api/chat": [crossing, () => streamOf(delta("Milk is on the list."), done)],
    });
    render(<Chat conversationId="c1" />);
    await screen.findByLabelText("Message");

    send(PROMPT);
    await capAlert(CROSSED);
    send(PROMPT);

    expect(await screen.findByText("Milk is on the list.")).toBeInTheDocument();
    expect(within(conversationList()).getAllByText(PROMPT)).toHaveLength(2);
    expect(chatBodies(calls)).toHaveLength(2);
    expect(chatBodies(calls)[1]).toMatchObject({ message: PROMPT, conversation_id: "c1" });
    expectKeptTurn();
    expect(screen.getByText(CROSSED)).toBeInTheDocument();
  });

  it("sends the same prompt as a new message after a reload of an answer that ended at the cap", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(
        200,
        detail({ messages: storedCrossing(), proposals: [wireProposal("p1", [EGGS], 3)] }),
      ),
      "POST /api/chat": () => streamOf(delta("Milk is on the list."), done),
    });
    render(<Chat conversationId="c1" />);
    await capAlert(STORED);

    send(PROMPT);

    expect(await screen.findByText("Milk is on the list.")).toBeInTheDocument();
    expect(within(conversationList()).getAllByText(PROMPT)).toHaveLength(2);
    expect(chatBodies(calls)).toEqual([
      { message: PROMPT, time_zone: browserTimeZone(), conversation_id: "c1" },
    ]);
    expectKeptTurn();
    expect(screen.getByText(STORED)).toBeInTheDocument();
  });

  it("shows a message refused before any turn once when it is sent again", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, detail()),
      "POST /api/chat": [
        () => errorResponse(409, "spend_cap_reached", REFUSED, { "X-Conversation-Id": "c1" }),
        () => streamOf(delta("Hi there."), done),
      ],
    });
    render(<Chat conversationId="c1" />);
    await screen.findByLabelText("Message");

    send("hello");
    await capAlert(REFUSED);
    send("hello");

    expect(await screen.findByText("Hi there.")).toBeInTheDocument();
    expect(within(conversationList()).getAllByText("hello")).toHaveLength(1);
    expect(chatBodies(calls)).toHaveLength(2);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
