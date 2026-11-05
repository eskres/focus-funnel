// @vitest-environment jsdom
// Answers that run on the server while the chat is away or its stream breaks:
// coming back to an answer (task 5.2) and following it again (task 5.3).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  openStream,
  proposalEvent,
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

const OAT: WirePart = { title: "Oat milk", summary: "Buy oat milk.", tags: ["groceries"], category: "task" };
const MILK = source("t1", "Milk run", "2026-08-02T09:00:00+00:00", ["groceries"]);
const CATEGORIES = { fixed: ["task", "idea", "decision", "note", "reference"], added: [] };
const STREAM = "GET /api/chat/c1/stream";
const DETAIL = "GET /api/conversations/c1";
const noTurn = () => new Response(null, { status: 204 });

const call = (id: string, name: string) => ({
  tool_calls: [{ id, type: "function", function: { name, arguments: "{}" } }],
});

/** An earlier exchange, then "/push milk" at position 2. */
const asked = [
  storedMessage(0, "user", "hi"),
  storedMessage(1, "assistant", "Hello."),
  storedMessage(2, "user", "/push milk"),
];

/** The rounds the turn for "/push milk" stores: a search, then a proposal. */
const rounds = [
  storedMessage(3, "assistant", null, call("a", "search_thoughts")),
  storedMessage(4, "tool", "1 match", { tool_call_id: "a", details: { sources: [MILK] } }),
  storedMessage(5, "assistant", null, call("b", "propose_thought")),
  storedMessage(6, "tool", "Proposed", { tool_call_id: "b", details: { proposal_id: "p1" } }),
];

/** The same turn's events, as the reattach replays them. */
const replayed = [
  toolEvent("search_thoughts", "start"),
  toolEvent("search_thoughts", "end", "Searched your thoughts", [MILK]),
  toolEvent("propose_thought", "start"),
  proposalEvent("p1", [OAT], 6),
  toolEvent("propose_thought", "end", "Proposed a thought to file"),
];

const running = (after = 2, messages = [...asked, ...rounds]) =>
  detail({
    messages,
    proposals: messages.length > 6 ? [wireProposal("p1", [OAT], 6)] : [],
    turn: { after_position: after },
  });

const finished = (last: Record<string, unknown> = {}) =>
  detail({
    messages: [...asked, ...rounds, storedMessage(7, "assistant", "Want to keep it?", last)],
    proposals: [wireProposal("p1", [OAT], 6)],
  });

function api(routes: Parameters<typeof fakeApi>[0]) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/settings/categories": json(200, CATEGORIES),
    ...routes,
  });
}

function open() {
  return render(
    <CategoriesProvider>
      <Chat conversationId="c1" />
    </CategoriesProvider>,
  );
}

function send(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

const input = () => screen.getByLabelText("Message");

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("coming back to an answer", () => {
  it("finished while away: shows the text, tools, proposal card, and sources, and lets the user send", async () => {
    const { calls } = api({
      [DETAIL]: [json(200, running()), json(200, finished())],
      [STREAM]: noTurn,
      "POST /api/conversations/c1/proposals/p1/confirm": json(200, {
        saved: true,
        thought_id: "t9",
        message: "Saved.",
      }),
    });
    open();

    expect(await screen.findByText("Want to keep it?")).toBeInTheDocument();
    const tools = screen.getAllByTestId("tool-indication").map((t) => t.textContent);
    expect(tools).toEqual(["Searched your thoughts", "Proposed a thought to file"]);
    const sources = screen.getByRole("region", { name: "Sources" });
    expect(within(sources).getByRole("link", { name: "Milk run" })).toBeInTheDocument();
    expect(screen.getAllByRole("region", { name: "Proposal to file" })).toHaveLength(1);
    // The 204 made the chat reload the stored conversation.
    expect(calls.map((c) => c.path)).toContain("/api/chat/c1/stream");
    expect(calls.filter((c) => c.path === "/api/conversations/c1")).toHaveLength(2);
    await waitFor(() => expect(input()).toBeEnabled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    // Proposal made while away: the card can be edited and confirmed.
    const card = screen.getByRole("group", { name: "Thought to file: Oat milk" });
    fireEvent.change(within(card).getByLabelText("Title"), { target: { value: "Oat and soy milk" } });
    fireEvent.click(within(card).getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("group", { name: "Saved: Oat and soy milk" })).toBeInTheDocument();
  });

  it("still running: shows the answer so far as in progress, then the rest, with the input locked", async () => {
    const stream = openStream();
    api({ [DETAIL]: json(200, running()), [STREAM]: () => stream.response });
    open();

    await stream.push(replayed.join("") + delta("Want to "));

    expect(await screen.findByText("Want to")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Writing");
    expect(input()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    // The stored rounds of the running turn show once, from the replay.
    expect(screen.getAllByTestId("tool-indication")).toHaveLength(2);
    expect(screen.getAllByRole("region", { name: "Proposal to file" })).toHaveLength(1);
    expect(screen.getByRole("region", { name: "Sources" })).toBeInTheDocument();
    expect(screen.getByText("Hello.")).toBeInTheDocument();

    await stream.push(delta("keep it?") + done);
    await stream.close();

    expect(await screen.findByText("Want to keep it?")).toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
  });

  it("still running with nothing stored yet: shows that the model is thinking", async () => {
    const stream = openStream();
    api({ [DETAIL]: json(200, running(2, asked)), [STREAM]: () => stream.response });
    open();

    expect(await screen.findByText("Thinking…")).toBeInTheDocument();
    expect(input()).toBeDisabled();
    expect(screen.getAllByText("/push milk")).toHaveLength(1);

    await stream.push(delta("Sure.") + done);
    await stream.close();
    expect(await screen.findByText("Sure.")).toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
  });

  it("failed while watching the return: shows the reason in place of the answer", async () => {
    api({
      [DETAIL]: json(200, running(2, asked)),
      [STREAM]: () =>
        new Response(errorEvent("output_limit_reached", "The model ran out of room."), {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
    });
    open();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The model ran out of room");
    await waitFor(() => expect(input()).toBeEnabled());
  });

  it.each([
    ["answer_interrupted", "The answer did not finish"],
    ["provider_unreachable", null],
  ])("failed while away (%s): shows the reason in place of the answer", async (code, title) => {
    api({
      [DETAIL]: [
        json(200, running(2, asked)),
        json(200, detail({
          messages: [...asked, storedMessage(3, "assistant", "Half", { status: "failed", error_code: code })],
        })),
      ],
      [STREAM]: noTurn,
    });
    open();

    const alert = await screen.findByRole("alert");
    if (title) expect(alert).toHaveTextContent(title);
    expect(alert).toHaveTextContent("This answer did not finish. Send the message again to retry.");
    if (code === "answer_interrupted") {
      expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    }
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
  });

  it("two chats on one answer both show it as it arrives", async () => {
    const first = openStream();
    const second = openStream();
    api({
      [DETAIL]: json(200, running(2, asked)),
      [STREAM]: [() => first.response, () => second.response],
    });
    const one = open();
    const two = open();
    await waitFor(() => expect(screen.getAllByText("Thinking…")).toHaveLength(2));

    await first.push(delta("Same answer."));
    await second.push(delta("Same answer."));

    for (const view of [one, two]) {
      const chat = within(view.container);
      expect(await chat.findByText("Same answer.")).toBeInTheDocument();
      expect(chat.getByLabelText("Message")).toBeDisabled();
    }

    await first.push(done);
    await first.close();
    await second.push(done);
    await second.close();
    for (const view of [one, two]) {
      await waitFor(() => expect(within(view.container).getByLabelText("Message")).toBeEnabled());
    }
  });

  it("stops following, and asks nothing else, when the user leaves", async () => {
    const stream = openStream();
    const { fetchMock, calls } = api({
      [DETAIL]: json(200, running(2, asked)),
      [STREAM]: () => stream.response,
    });
    const view = open();
    await screen.findByText("Thinking…");
    const [, init] = fetchMock.mock.calls.find(([url]) => String(url) === "/api/chat/c1/stream") as unknown as [
      string,
      RequestInit,
    ];
    expect(init.signal?.aborted).toBe(false);
    const before = calls.length;

    view.unmount();

    expect(init.signal?.aborted).toBe(true);
    // Nothing stops the answer on the server: no request goes out.
    expect(calls).toHaveLength(before);
  });
});

describe("following an answer again after the connection breaks", () => {
  const before = detail({ messages: asked.slice(0, 2) });

  /** Opens c1, sends "/push milk", receives `text`, and then the connection breaks. */
  async function breakAfter(
    text: string,
    routes: Parameters<typeof fakeApi>[0],
    end: "fail" | "close" = "fail",
  ) {
    const post = openStream();
    const fake = api({ "POST /api/chat": () => post.response, ...routes });
    open();
    await screen.findByText("Hello.");
    send("/push milk");
    await post.push(delta(text));
    await screen.findByText(text);
    await (end === "fail" ? post.fail() : post.close());
    return fake;
  }

  it("connection drops in the middle: keeps the part received and shows the rest as it arrives", async () => {
    const follow = openStream();
    const { calls } = await breakAfter("Half an ans", {
      [DETAIL]: [json(200, before), json(200, running(2, asked))],
      [STREAM]: () => follow.response,
    });

    // Following again: what arrived stays, and the input stays locked.
    await waitFor(() => expect(calls.map((c) => c.path)).toContain("/api/chat/c1/stream"));
    expect(screen.getAllByText("/push milk")).toHaveLength(1);
    expect(screen.getByText("Half an ans")).toBeInTheDocument();
    expect(input()).toBeDisabled();
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();

    // The replay starts from the first event, so nothing shows twice.
    await follow.push(delta("Half an ans"));
    expect(screen.getByText("Half an ans")).toBeInTheDocument();
    await follow.push(delta("wer.") + done);
    await follow.close();

    expect(await screen.findByText("Half an answer.")).toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
    expect(screen.getAllByText("/push milk")).toHaveLength(1);
  });

  it("a new conversation's stream that closes early is followed in that conversation", async () => {
    const post = openStream();
    const follow = openStream();
    const { calls } = api({
      "GET /api/settings/models": json(200, loadout()),
      "POST /api/chat": () => post.response,
      [DETAIL]: json(200, running(2, asked)),
      [STREAM]: () => follow.response,
    });
    render(<Chat />);
    send("/push milk");
    await post.push(conversationEvent("c1", "Milk") + delta("Hal"));
    await post.close();

    await follow.push(conversationEvent("c1", "Milk") + delta("Half done.") + done);
    await follow.close();

    expect(await screen.findByText("Half done.")).toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
    expect(calls.map((c) => c.path)).toEqual(
      expect.arrayContaining(["/api/conversations/c1", "/api/chat/c1/stream"]),
    );
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
  });

  it("connection drops and the answer ends meanwhile: shows the stored answer, not cut short", async () => {
    const { calls } = await breakAfter("Want", {
      [DETAIL]: [json(200, before), json(200, finished())],
    });

    expect(await screen.findByText("Want to keep it?")).toBeInTheDocument();
    expect(screen.getAllByRole("region", { name: "Proposal to file" })).toHaveLength(1);
    expect(screen.getByRole("region", { name: "Sources" })).toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
    expect(calls.map((c) => c.path)).not.toContain("/api/chat/c1/stream");
  });

  it("connection drops and the stored answer did not finish: says it was cut short", async () => {
    await breakAfter("Want", {
      [DETAIL]: [json(200, before), json(200, finished({ status: "cut" }))],
    });

    expect(await screen.findByText(/cut short/)).toBeInTheDocument();
    expect(screen.getByText("Want to keep it?")).toBeInTheDocument();
    expect(screen.queryByText(/Open the conversation again/)).not.toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
  });

  it("connection drops and no answer was stored: keeps the part received and says it was cut short", async () => {
    await breakAfter("Want", {
      [DETAIL]: [json(200, before), json(200, detail({ messages: asked }))],
    }, "close");

    expect(await screen.findByText(/cut short/)).toBeInTheDocument();
    expect(screen.getByText("Want")).toBeInTheDocument();
  });

  it("connection drops and the answer stops at the tool round limit: shows that reason, not cut short", async () => {
    await breakAfter("Let me", {
      [DETAIL]: [
        json(200, before),
        json(200, detail({
          messages: [
            ...asked,
            storedMessage(3, "assistant", "Let me look.", { ...call("a", "search_thoughts"), error_code: "tool_loop_limit" }),
            storedMessage(4, "tool", "1 match", { tool_call_id: "a", details: { sources: [MILK] } }),
          ],
        })),
      ],
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The answer could not be completed");
    expect(screen.getByText("Let me look.")).toBeInTheDocument();
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
  });

  it("follows again at most three times, then says the answer was cut short", async () => {
    // Every follow stream closes before the answer ends, and the turn keeps running.
    const breaks = () =>
      new Response(delta("Half an ans"), { status: 200, headers: { "Content-Type": "text/event-stream" } });
    const { calls } = await breakAfter("Half an ans", {
      [DETAIL]: [json(200, before), json(200, running(2, asked))],
      [STREAM]: breaks,
    });

    expect(await screen.findByText(/cut short/)).toBeInTheDocument();
    expect(screen.queryByText(/Open the conversation again/)).not.toBeInTheDocument();
    expect(screen.getByText("Half an ans")).toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
    expect(calls.filter((c) => c.path === "/api/chat/c1/stream")).toHaveLength(3);
  });

  it("a follow the server refuses (the conversation was deleted): shows that error, not cut short", async () => {
    const { calls } = await breakAfter("Half an ans", {
      [DETAIL]: [json(200, before), json(200, running(2, asked))],
      [STREAM]: errorResponse(404, "not_found", "Not found."),
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Not found.");
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
    // The refusal is final: the conversation is not reloaded and followed again.
    expect(calls.filter((c) => c.path === "/api/chat/c1/stream")).toHaveLength(1);
    expect(calls.filter((c) => c.path === "/api/conversations/c1")).toHaveLength(2);
  });

  it("server cannot be reached again: keeps the part received, says it was cut short and to open it again", async () => {
    await breakAfter("Half an ans", {
      [DETAIL]: [
        json(200, before),
        () => {
          throw new TypeError("Failed to fetch");
        },
      ],
    });

    expect(await screen.findByText(/cut short/)).toHaveTextContent(
      "Open the conversation again later to see if it finished.",
    );
    expect(screen.getByText("Half an ans")).toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
  });

  it("server cannot be reached while following again: keeps the part received and says it was cut short", async () => {
    const follow = openStream();
    await breakAfter("Half an ans", {
      [DETAIL]: [
        json(200, before),
        json(200, running(2, asked)),
        () => {
          throw new TypeError("Failed to fetch");
        },
      ],
      [STREAM]: () => follow.response,
    });
    await follow.push(delta("Half an answ"));
    await follow.fail();

    expect(await screen.findByText(/cut short/)).toHaveTextContent("Open the conversation again");
    expect(screen.getByText("Half an answ")).toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
  });
});
