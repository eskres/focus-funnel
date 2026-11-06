// @vitest-environment jsdom
// The chat's Stop button (stop-and-spend-cap task 5.3, design decision 5).
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { browserTimeZone } from "@/lib/time-zone";
import {
  conversationEvent,
  delta,
  detail,
  done,
  errorEvent,
  errorResponse,
  fakeApi,
  json,
  loadout,
  loadoutEntry,
  openStream,
  source,
  storedMessage,
  toolEvent,
  wireProposal,
  type WirePart,
} from "@/test/fake-api";

import { CategoriesProvider } from "./categories-context";
import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const NANO = "vendor/nano";
const CATEGORIES = { fixed: ["task", "idea", "decision", "note", "reference"], added: [] };
const OAT: WirePart = { title: "Oat milk", summary: "Buy oat milk.", tags: ["groceries"], category: "task" };
const MILK = source("t1", "Milk run", "2026-08-02T09:00:00+00:00", ["groceries"]);
const STOPPED = "You stopped this answer.";
const STOP = "POST /api/chat/c1/stop";
const DETAIL = "GET /api/conversations/c1";
const STREAM = "GET /api/chat/c1/stream";
const stopped204 = () => new Response(null, { status: 204 });
const noTurn = () => new Response(null, { status: 204 });
const answerStopped = errorEvent("answer_stopped", STOPPED);

const asked = [storedMessage(0, "user", "about rent"), storedMessage(1, "assistant", "Tell me more.")];

/** A stopped answer as the server stores it. */
const stoppedMessage = (position: number, content: string | null, extra: Record<string, unknown> = {}) =>
  storedMessage(position, "assistant", content, {
    status: "stopped",
    error_code: "answer_stopped",
    ...extra,
  });

const call = (id: string, name: string) => ({
  tool_calls: [{ id, type: "function", function: { name, arguments: "{}" } }],
});

function api(routes: Parameters<typeof fakeApi>[0]) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout([loadoutEntry(NANO, { is_default: true })])),
    "GET /api/settings/categories": json(200, CATEGORIES),
    ...routes,
  });
}

function open(conversationId?: string) {
  return render(
    <CategoriesProvider>
      <Chat conversationId={conversationId} />
    </CategoriesProvider>,
  );
}

function send(text: string, within_: ReturnType<typeof within> | typeof screen = screen) {
  fireEvent.change(within_.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(within_.getByRole("button", { name: "Send" }));
}

const input = () => screen.getByLabelText("Message");
const stopButton = () => screen.getByRole("button", { name: "Stop" });
const stopsSent = (calls: { method: string; path: string }[]) =>
  calls.filter((c) => c.method === "POST" && c.path === "/api/chat/c1/stop");
const chatBodies = (calls: { method: string; path: string; body: unknown }[]) =>
  calls.filter((c) => c.path === "/api/chat").map((c) => c.body as Record<string, unknown>);

/** Opens conversation c1 and sends `text` on a live stream; Stop is ready once the stream opened. */
async function sendInStored(stream: ReturnType<typeof openStream>, routes: Parameters<typeof fakeApi>[0] = {}) {
  const fake = api({
    [DETAIL]: json(200, detail({ messages: asked })),
    "POST /api/chat": () => stream.response,
    [STOP]: stopped204,
    ...routes,
  });
  open("c1");
  await screen.findByText("Tell me more.");
  send("what about rent?");
  await waitFor(() => expect(stopButton()).toBeEnabled());
  return fake;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/app");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("Stop", () => {
  it("is disabled until the stream has started and the conversation id is known", async () => {
    const stream = openStream();
    let answer!: () => void;
    const answered = new Promise<void>((resolve) => (answer = resolve));
    const { calls } = api({
      "POST /api/chat": async () => {
        await answered;
        return stream.response;
      },
      "POST /api/chat/c7/stop": stopped204,
    });
    open();
    await screen.findByRole("option", { name: NANO });

    send("hello");

    // The POST has not answered: the server has no turn to stop yet.
    const button = await screen.findByRole("button", { name: "Stop" });
    expect(button).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();

    // The stream started, but a new conversation's id comes in its first event.
    await act(async () => answer());
    await waitFor(() => expect(calls.filter((c) => c.path === "/api/chat")).toHaveLength(1));
    expect(stopButton()).toBeDisabled();

    await stream.push(conversationEvent("c7", "hello"));
    await waitFor(() => expect(stopButton()).toBeEnabled());

    fireEvent.click(stopButton());
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "POST" && c.path === "/api/chat/c7/stop")).toHaveLength(1),
    );
    await stream.push(answerStopped);
    await stream.close();
    expect(await screen.findByText(STOPPED)).toBeInTheDocument();
  });

  it("posts the stop without aborting the stream; answer_stopped keeps the text, shows the note, and unlocks", async () => {
    const stream = openStream();
    const { calls, fetchMock } = await sendInStored(stream);
    await stream.push(delta("Rent is due "));
    expect(await screen.findByText("Rent is due")).toBeInTheDocument();

    fireEvent.click(stopButton());

    await waitFor(() => expect(stopsSent(calls)).toHaveLength(1));
    const chatCall = fetchMock.mock.calls.find(([path]) => String(path) === "/api/chat")!;
    const signal = (chatCall[1] as RequestInit).signal!;
    expect(signal.aborted).toBe(false);
    // The stream is still read: text sent before the stop took effect shows.
    await stream.push(delta("on the first."));
    expect(await screen.findByText("Rent is due on the first.")).toBeInTheDocument();

    await stream.push(answerStopped);
    await stream.close();

    expect(await screen.findByText(STOPPED)).toBeInTheDocument();
    expect(screen.getByText("Rent is due on the first.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(signal.aborted).toBe(false);
    expect(stopsSent(calls)).toHaveLength(1);
  });

  it("before the first delta ends the thinking indication and shows the note", async () => {
    const stream = openStream();
    await sendInStored(stream);
    expect(screen.getByText("Thinking…")).toBeInTheDocument();

    fireEvent.click(stopButton());
    await stream.push(answerStopped);
    await stream.close();

    expect(await screen.findByText(STOPPED)).toBeInTheDocument();
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
  });

  it("keeps Stopping… after the stop answered 204, until the terminal event", async () => {
    const stream = openStream();
    const { calls } = await sendInStored(stream);
    await stream.push(delta("Rent "));

    fireEvent.click(stopButton());
    await waitFor(() => expect(stopsSent(calls)).toHaveLength(1));
    // Let the 204 settle.
    await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));

    const stopping = screen.getByRole("button", { name: "Stopping…" });
    expect(stopping).toBeDisabled();
    expect(input()).toBeDisabled();

    await stream.push(answerStopped);
    await stream.close();

    await waitFor(() => expect(screen.queryByRole("button", { name: "Stopping…" })).not.toBeInTheDocument());
    await waitFor(() => expect(input()).toBeEnabled());
  });

  it("after Stop, a done event shows the complete answer with no note and unlocks", async () => {
    const stream = openStream();
    const { calls } = await sendInStored(stream);
    await stream.push(delta("Rent is 900."));

    fireEvent.click(stopButton());
    await waitFor(() => expect(stopsSent(calls)).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Stopping…" })).toBeInTheDocument();

    await stream.push(done);
    await stream.close();

    await waitFor(() => expect(input()).toBeEnabled());
    expect(screen.getByText("Rent is 900.")).toBeInTheDocument();
    expect(screen.queryByText(STOPPED)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stopping…" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("after Stop, a spend_cap_reached event shows the cap alert and unlocks", async () => {
    const stream = openStream();
    const { calls } = await sendInStored(stream);

    fireEvent.click(stopButton());
    await waitFor(() => expect(stopsSent(calls)).toHaveLength(1));
    await stream.push(errorEvent("spend_cap_reached", "You reached your monthly spend cap of $5.00."));
    await stream.close();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Monthly spend cap reached");
    expect(alert).toHaveTextContent("You reached your monthly spend cap of $5.00.");
    expect(screen.queryByText(STOPPED)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stopping…" })).not.toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
  });

  it("during a search_thoughts start shows 'Stopped before it finished', and a reload shows the same line", async () => {
    const stream = openStream();
    await sendInStored(stream);
    await stream.push(toolEvent("search_thoughts", "start"));
    expect(await screen.findByText("Searching your thoughts…")).toBeInTheDocument();

    fireEvent.click(stopButton());
    await stream.push(answerStopped);
    await stream.close();

    expect(await screen.findByText(STOPPED)).toBeInTheDocument();
    const live = screen.getAllByTestId("tool-indication");
    expect(live.map((t) => t.textContent)).toEqual(["Stopped before it finished"]);
    expect(live[0]).toHaveAttribute("data-state", "stopped");
    expect(screen.queryByText("Searching your thoughts…")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    const shown = live.map((t) => t.textContent);

    // The server stored the cut-off call's name on the stopped message, with no tool_calls.
    cleanup();
    api({
      [DETAIL]: json(
        200,
        detail({
          messages: [
            ...asked,
            storedMessage(2, "user", "what about rent?"),
            stoppedMessage(3, null, { details: { stopped_tools: ["search_thoughts"] } }),
          ],
        }),
      ),
    });
    open("c1");

    expect(await screen.findByText(STOPPED)).toBeInTheDocument();
    expect(screen.getAllByTestId("tool-indication").map((t) => t.textContent)).toEqual(shown);
    expect(screen.queryByText("Searching your thoughts…")).not.toBeInTheDocument();
  });

  it("reloaded: a tool message with details.stopped shows 'Stopped before it finished', not its done label", async () => {
    api({
      [DETAIL]: json(
        200,
        detail({
          messages: [
            ...asked,
            storedMessage(2, "user", "what about rent?"),
            storedMessage(3, "assistant", null, call("a", "search_thoughts")),
            storedMessage(4, "tool", "Not run: the user stopped the answer before this tool finished.", {
              tool_call_id: "a",
              details: { stopped: true },
            }),
            stoppedMessage(5, null),
          ],
        }),
      ),
    });
    open("c1");

    expect(await screen.findByText(STOPPED)).toBeInTheDocument();
    expect(screen.getAllByTestId("tool-indication").map((t) => t.textContent)).toEqual([
      "Stopped before it finished",
    ]);
    expect(screen.queryByText("Searched your thoughts")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("when the POST stream drops and the follow route answers 204, a stored stopped answer shows the note, not cut short", async () => {
    const stream = openStream();
    const runningDetail = detail({
      messages: [...asked, storedMessage(2, "user", "what about rent?")],
      turn: { after_position: 2 },
    });
    const stoppedDetail = detail({
      messages: [...asked, storedMessage(2, "user", "what about rent?"), stoppedMessage(3, "Rent is ")],
    });
    const { calls } = api({
      [DETAIL]: [json(200, detail({ messages: asked })), json(200, runningDetail), json(200, stoppedDetail)],
      "POST /api/chat": () => stream.response,
      [STOP]: stopped204,
      [STREAM]: noTurn,
    });
    open("c1");
    await screen.findByText("Tell me more.");
    send("what about rent?");
    await waitFor(() => expect(stopButton()).toBeEnabled());
    await stream.push(delta("Rent is "));
    fireEvent.click(stopButton());
    await waitFor(() => expect(stopsSent(calls)).toHaveLength(1));

    await stream.close();

    expect(await screen.findByText(STOPPED)).toBeInTheDocument();
    expect(screen.getByText("Rent is")).toBeInTheDocument();
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
    expect(calls.map((c) => c.path)).toContain("/api/chat/c1/stream");
    await waitFor(() => expect(input()).toBeEnabled());
    expect(screen.queryByRole("button", { name: "Stopping…" })).not.toBeInTheDocument();
  });

  it("shows Stop when following a running turn after coming back, and ends the same way", async () => {
    const stream = openStream();
    const { calls } = api({
      [DETAIL]: json(
        200,
        detail({ messages: [...asked, storedMessage(2, "user", "what about rent?")], turn: { after_position: 2 } }),
      ),
      [STREAM]: () => stream.response,
      [STOP]: stopped204,
    });
    open("c1");

    await waitFor(() => expect(stopButton()).toBeEnabled());
    await stream.push(delta("Rent is "));
    expect(await screen.findByText("Rent is")).toBeInTheDocument();

    fireEvent.click(stopButton());
    await waitFor(() => expect(stopsSent(calls)).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Stopping…" })).toBeDisabled();
    await stream.push(answerStopped);
    await stream.close();

    expect(await screen.findByText(STOPPED)).toBeInTheDocument();
    expect(screen.getByText("Rent is")).toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ends both chats on one turn stopped when one presses Stop", async () => {
    const sent = openStream();
    const followed = openStream();
    const { calls } = api({
      [DETAIL]: [
        json(200, detail({ messages: asked })),
        json(
          200,
          detail({ messages: [...asked, storedMessage(2, "user", "what about rent?")], turn: { after_position: 2 } }),
        ),
      ],
      "POST /api/chat": () => sent.response,
      [STREAM]: () => followed.response,
      [STOP]: stopped204,
    });
    const first = within(open("c1").container);
    await first.findByText("Tell me more.");
    send("what about rent?", first);
    await waitFor(() => expect(first.getByRole("button", { name: "Stop" })).toBeEnabled());

    // A second tab opens the same conversation and follows the running turn.
    const second = within(open("c1").container);
    await waitFor(() => expect(second.getByRole("button", { name: "Stop" })).toBeEnabled());

    await sent.push(delta("Rent "));
    await followed.push(delta("Rent "));
    fireEvent.click(second.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(stopsSent(calls)).toHaveLength(1));

    // Both read the same log: each gets the terminal event.
    await sent.push(answerStopped);
    await sent.close();
    await followed.push(answerStopped);
    await followed.close();

    expect(await first.findByText(STOPPED)).toBeInTheDocument();
    expect(await second.findByText(STOPPED)).toBeInTheDocument();
    await waitFor(() => expect(first.getByLabelText("Message")).toBeEnabled());
    await waitFor(() => expect(second.getByLabelText("Message")).toBeEnabled());
    expect(stopsSent(calls)).toHaveLength(1);
  });

  it("says when the stop failed, and Stop can be pressed again", async () => {
    const stream = openStream();
    const { calls } = await sendInStored(stream, {
      [STOP]: [errorResponse(500, "internal_error", "Something went wrong."), stopped204()],
    });
    await stream.push(delta("Rent "));

    fireEvent.click(stopButton());

    expect(await screen.findByText("The answer could not be stopped. Try again.")).toBeInTheDocument();
    await waitFor(() => expect(stopButton()).toBeEnabled());
    expect(input()).toBeDisabled();

    fireEvent.click(stopButton());
    await waitFor(() => expect(stopsSent(calls)).toHaveLength(2));
    await waitFor(() =>
      expect(screen.queryByText("The answer could not be stopped. Try again.")).not.toBeInTheDocument(),
    );
    await stream.push(answerStopped);
    await stream.close();
    expect(await screen.findByText(STOPPED)).toBeInTheDocument();
  });

  it("reloaded: a stopped answer shows the note with its tools, sources, and proposal card", async () => {
    api({
      [DETAIL]: json(
        200,
        detail({
          messages: [
            ...asked,
            storedMessage(2, "user", "/push milk"),
            storedMessage(3, "assistant", null, call("a", "search_thoughts")),
            storedMessage(4, "tool", "1 match", {
              tool_call_id: "a",
              details: { sources: [MILK], summary: "Searched your thoughts" },
            }),
            storedMessage(5, "assistant", null, call("b", "propose_thought")),
            storedMessage(6, "tool", "Proposed", {
              tool_call_id: "b",
              details: { proposal_id: "p1", summary: "Proposed a thought to file" },
            }),
            stoppedMessage(7, "Want to keep"),
          ],
          proposals: [wireProposal("p1", [OAT], 6)],
        }),
      ),
    });
    open("c1");

    expect(await screen.findByText(STOPPED)).toBeInTheDocument();
    expect(screen.getByText("Want to keep")).toBeInTheDocument();
    expect(screen.getAllByTestId("tool-indication").map((t) => t.textContent)).toEqual([
      "Searched your thoughts",
      "Proposed a thought to file",
    ]);
    const sources = screen.getByRole("region", { name: "Sources" });
    expect(within(sources).getByRole("link", { name: "Milk run" })).toBeInTheDocument();
    expect(screen.getAllByRole("region", { name: "Proposal to file" })).toHaveLength(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(input()).toBeEnabled();
  });

  it("is not offered for /compact", async () => {
    const stream = openStream();
    api({
      [DETAIL]: json(200, detail({ messages: asked })),
      "POST /api/conversations/c1/proposal": json(200, { proposal: null }),
      "POST /api/chat": () => stream.response,
    });
    open("c1");
    await screen.findByText("Tell me more.");

    send("/compact");

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Writing a summary…");
    // The dialog keeps its Cancel; the composer behind it offers no Stop.
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    await waitFor(() => expect(input()).toBeDisabled());
    expect(screen.queryByRole("button", { name: /^Stop/, hidden: true })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send", hidden: true })).toBeDisabled();
    await stream.close();
  });

  it("sends the same text again after a stop as a new message", async () => {
    const stream = openStream();
    const again = openStream();
    const { calls } = await sendInStored(stream, {
      "POST /api/chat": [() => stream.response, () => again.response],
    });
    await stream.push(delta("Rent "));
    fireEvent.click(stopButton());
    await stream.push(answerStopped);
    await stream.close();
    await screen.findByText(STOPPED);
    await waitFor(() => expect(input()).toBeEnabled());

    send("what about rent?");
    await again.push(delta("Rent is 900.") + done);
    await again.close();

    expect(await screen.findByText("Rent is 900.")).toBeInTheDocument();
    // The stopped answer stays, and the message shows twice.
    expect(screen.getByText(STOPPED)).toBeInTheDocument();
    expect(screen.getByText("Rent")).toBeInTheDocument();
    expect(screen.getAllByText("what about rent?")).toHaveLength(2);
    expect(chatBodies(calls)).toEqual([
      { message: "what about rent?", time_zone: browserTimeZone(), conversation_id: "c1" },
      { message: "what about rent?", time_zone: browserTimeZone(), conversation_id: "c1" },
    ]);
  });
});
