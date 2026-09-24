// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { redirectToLogin } from "@/lib/redirect-to-login";
import {
  conversationEvent,
  delta,
  done,
  errorEvent,
  errorResponse,
  fakeApi,
  json,
  loadout,
  loadoutEntry,
  openStream,
  storedMessage,
  streamOf,
  toolEvent,
} from "@/test/fake-api";

import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/app",
}));

const NANO = "vendor/nano";
const BIG = "vendor/big";
const withDefault = loadout([
  loadoutEntry(NANO, { is_default: true, reasoning_effort: "low" }),
  loadoutEntry(BIG, { efforts: ["low", "medium", "high"] }),
]);

function conversation(extra: Record<string, unknown> = {}) {
  return {
    id: "c1",
    title: "Rent",
    provider_id: "nebius",
    model: NANO,
    reasoning_effort: null,
    archived: false,
    last_activity_at: "2026-09-23T10:00:00Z",
    created_at: "2026-09-23T10:00:00Z",
    last_prompt_tokens: null,
    held_proposal_id: null,
    proposals: [],
    messages: [storedMessage(0, "user", "about rent"), storedMessage(1, "assistant", "Tell me more.")],
    ...extra,
  };
}

function send(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

function chatBodies(calls: { method: string; path: string; body: unknown }[]) {
  return calls.filter((c) => c.path === "/api/chat").map((c) => c.body as Record<string, unknown>);
}

beforeEach(() => {
  window.history.replaceState(null, "", "/app");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("Chat", () => {
  describe("an empty conversation", () => {
    it("lists /push, /pull, /explore, and /compact, and not /delete", async () => {
      fakeApi({ "GET /api/settings/models": json(200, withDefault) });
      render(<Chat />);

      for (const command of ["/push", "/pull", "/explore", "/compact"]) {
        expect(screen.getByText(command, { selector: "code" })).toBeInTheDocument();
      }
      expect(screen.queryByText("/delete")).not.toBeInTheDocument();
      expect(screen.queryByText(/delete/i)).not.toBeInTheDocument();
    });
  });

  describe("sending", () => {
    it("adds the user's message, clears the input, and sends the message", async () => {
      const stream = openStream();
      const { calls } = fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "POST /api/chat": () => stream.response,
      });
      render(<Chat />);
      await screen.findByRole("option", { name: NANO });

      send("buy oat milk");

      const list = await screen.findByRole("list", { name: "Conversation" });
      expect(within(list).getByText("buy oat milk")).toBeInTheDocument();
      expect(screen.getByLabelText("Message")).toHaveValue("");
      expect(chatBodies(calls)[0]).toMatchObject({ message: "buy oat milk" });
      await stream.close();
    });

    it.each(["", "   ", "\n\t "])("sends nothing for the message %j", async (text) => {
      const { calls } = fakeApi({ "GET /api/settings/models": json(200, withDefault) });
      render(<Chat />);

      send(text);

      expect(chatBodies(calls)).toEqual([]);
      expect(screen.queryByRole("list", { name: "Conversation" })).not.toBeInTheDocument();
    });

    it("sends on Enter and adds a line on Shift+Enter", async () => {
      const { calls } = fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "POST /api/chat": () => streamOf(delta("Hi"), done),
      });
      render(<Chat />);
      const input = screen.getByLabelText("Message");
      fireEvent.change(input, { target: { value: "hello" } });

      fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
      expect(chatBodies(calls)).toEqual([]);

      fireEvent.keyDown(input, { key: "Enter" });
      await waitFor(() => expect(chatBodies(calls)).toHaveLength(1));
    });

    it("disables the composer while an answer arrives and enables it after", async () => {
      const stream = openStream();
      fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "POST /api/chat": () => stream.response,
      });
      render(<Chat />);

      send("hello");

      await waitFor(() => expect(screen.getByLabelText("Message")).toBeDisabled());
      expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

      await stream.push(delta("Hi") + done);
      await stream.close();

      await waitFor(() => expect(screen.getByLabelText("Message")).toBeEnabled());
    });

    it("shows that the model is thinking before the first text, then the text", async () => {
      const stream = openStream();
      fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "POST /api/chat": () => stream.response,
      });
      render(<Chat />);

      send("hello");

      expect(await screen.findByText("Thinking…")).toBeInTheDocument();

      await stream.push(delta("\nHi "));
      expect(await screen.findByText("Hi")).toBeInTheDocument();
      expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent("Writing");

      await stream.push(delta("there.") + done);
      await stream.close();
      await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
      expect(screen.getByText("Hi there.")).toBeInTheDocument();
    });

    it("shows a tool indication before the text that follows it", async () => {
      const stream = openStream();
      fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "POST /api/chat": () => stream.response,
      });
      render(<Chat />);

      send("what did I say about rent?");
      await stream.push(toolEvent("search_thoughts", "start"));

      const indication = await screen.findByTestId("tool-indication");
      expect(indication).toHaveTextContent("Searching your thoughts…");
      expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();

      await stream.push(toolEvent("search_thoughts", "end", "Searched your thoughts for “rent”"));
      await stream.push(delta("Search is not available yet."));
      expect(await screen.findByText("Search is not available yet.")).toBeInTheDocument();
      expect(screen.getByTestId("tool-indication")).toHaveTextContent(
        "Searched your thoughts for “rent”",
      );
      const answer = screen.getByText("Search is not available yet.").closest("li")!;
      expect(answer.firstElementChild).toBe(screen.getByTestId("tool-indication"));
      await stream.close();
    });

    it("moves to the new conversation's address and keeps sending there", async () => {
      const { calls } = fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "POST /api/chat": [
          () => streamOf(conversationEvent("c7", "hello"), delta("Hi"), done),
          () => streamOf(delta("Again"), done),
        ],
      });
      render(<Chat />);
      await screen.findByRole("option", { name: NANO });

      send("hello");
      await screen.findByText("Hi");
      expect(window.location.pathname).toBe("/app/c7");

      send("again");
      await screen.findByText("Again");
      expect(chatBodies(calls)[1]).toEqual({ message: "again", conversation_id: "c7" });
    });
  });

  describe("resuming a conversation", () => {
    it("loads and shows every stored message", async () => {
      fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "GET /api/conversations/c1": json(
          200,
          conversation({
            messages: [
              storedMessage(0, "user", "what about milk?"),
              storedMessage(1, "assistant", null, {
                tool_calls: [
                  {
                    id: "t",
                    type: "function",
                    function: { name: "search_thoughts", arguments: "{}" },
                  },
                ],
              }),
              storedMessage(2, "tool", "not available", { tool_call_id: "t" }),
              storedMessage(3, "assistant", "Not available yet."),
              storedMessage(4, "user", "ok"),
            ],
          }),
        ),
      });
      render(<Chat conversationId="c1" />);

      const list = await screen.findByRole("list", { name: "Conversation" });
      expect(within(list).getByText("what about milk?")).toBeInTheDocument();
      expect(within(list).getByText("Searched your thoughts")).toBeInTheDocument();
      expect(within(list).getByText("Not available yet.")).toBeInTheDocument();
      expect(within(list).getByText("ok")).toBeInTheDocument();
      expect(within(list).queryByText("not available")).not.toBeInTheDocument();
    });
  });

  describe("choosing a model", () => {
    it("starts a new conversation from the default model and effort", async () => {
      fakeApi({ "GET /api/settings/models": json(200, withDefault) });
      render(<Chat />);

      await waitFor(() => expect(screen.getByLabelText("Model")).toHaveDisplayValue(NANO));
      expect(screen.getByLabelText("Reasoning effort")).toHaveDisplayValue("low");
      expect(screen.getByRole("link", { name: "Model settings" })).toHaveAttribute(
        "href",
        "/settings#models",
      );
    });

    it("sends a chosen model with the next message", async () => {
      const { calls } = fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "GET /api/conversations/c1": json(200, conversation()),
        "POST /api/chat": [
          () => streamOf(delta("Big here."), done),
          () => streamOf(delta("Still big."), done),
        ],
      });
      render(<Chat conversationId="c1" />);
      await screen.findByText("Tell me more.");

      fireEvent.change(screen.getByLabelText("Model"), { target: { value: `nebius\u0000${BIG}` } });
      fireEvent.change(screen.getByLabelText("Reasoning effort"), { target: { value: "high" } });
      send("next");
      await screen.findByText("Big here.");
      send("and more");
      await screen.findByText("Still big.");

      expect(chatBodies(calls)).toEqual([
        {
          message: "next",
          conversation_id: "c1",
          provider_id: "nebius",
          model: BIG,
          reasoning_effort: "high",
        },
        // The choice is stored with the conversation, so it is not sent again.
        { message: "and more", conversation_id: "c1" },
      ]);
    });

    it("shows the default model for a conversation that has no model yet", async () => {
      fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "GET /api/conversations/c1": json(
          200,
          conversation({ provider_id: null, model: null, messages: [storedMessage(0, "user", "hi")] }),
        ),
      });
      render(<Chat conversationId="c1" />);

      await waitFor(() => expect(screen.getByLabelText("Model")).toHaveDisplayValue(NANO));
    });

    it("offers only the efforts the table allows", async () => {
      fakeApi({
        "GET /api/settings/models": json(
          200,
          loadout([loadoutEntry(NANO, { is_default: true, efforts: ["low", "medium", "high"] })]),
        ),
      });
      render(<Chat />);

      const effort = await screen.findByLabelText("Reasoning effort");
      const offered = within(effort)
        .getAllByRole("option")
        .map((o) => o.textContent);
      expect(offered).toEqual(["Default effort", "low", "medium", "high"]);
    });

    it("lists the conversation's own model, marked, when it left the loadout", async () => {
      fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "GET /api/conversations/c1": json(200, conversation({ model: "vendor/old" })),
        "GET /api/settings/models/efforts": json(200, { efforts: ["low"] }),
      });
      render(<Chat conversationId="c1" />);

      const model = await screen.findByLabelText("Model");
      await waitFor(() => expect(model).toHaveDisplayValue("vendor/old (not in your loadout)"));
      expect(within(model).getByRole("option", { name: NANO })).toBeInTheDocument();
    });
  });

  describe("/delete", () => {
    function openStored() {
      return fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "GET /api/conversations/c1": json(200, conversation()),
        "DELETE /api/conversations/c1": new Response(null, { status: 204 }),
      });
    }

    it("asks, then deletes the conversation and opens a new one", async () => {
      const { calls } = openStored();
      render(<Chat conversationId="c1" />);
      await screen.findByText("Tell me more.");

      send("/delete");

      const dialog = await screen.findByRole("dialog");
      expect(dialog).toHaveTextContent("Delete this conversation?");
      expect(dialog).toHaveTextContent("Rent");
      fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

      await waitFor(() => expect(push).toHaveBeenCalledWith("/app"));
      expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/conversations/c1")).toBe(
        true,
      );
      expect(chatBodies(calls)).toEqual([]);
    });

    it("changes nothing when cancelled", async () => {
      const { calls } = openStored();
      render(<Chat conversationId="c1" />);
      await screen.findByText("Tell me more.");

      send("/delete");
      fireEvent.click(
        within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }),
      );

      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
      expect(calls.some((c) => c.method === "DELETE")).toBe(false);
      expect(screen.getByText("Tell me more.")).toBeInTheDocument();
      expect(push).not.toHaveBeenCalled();
    });
  });

  describe("errors", () => {
    function failWith(handler: () => Response) {
      return fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "POST /api/chat": handler,
      });
    }

    it.each([
      ["provider_key_missing", 409, "No API key saved", "Go to provider settings", "/settings"],
      [
        "provider_key_rejected",
        409,
        "Your API key no longer works",
        "Go to provider settings",
        "/settings",
      ],
      ["model_not_set", 409, "No chat model chosen", "Go to model settings", "/settings#models"],
      [
        "model_unavailable",
        409,
        "This model is not available",
        "Go to model settings",
        "/settings#models",
      ],
    ])("%s links to the place that fixes it", async (code, status, title, link, href) => {
      failWith(() => errorResponse(status, code, "The backend's message."));
      render(<Chat />);

      send("hello");

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(title);
      expect(alert).toHaveTextContent("The backend's message.");
      expect(within(alert).getByRole("link", { name: link })).toHaveAttribute("href", href);
      expect(screen.getByText("hello")).toBeInTheDocument();
    });

    it("model_unavailable names the model", async () => {
      failWith(() =>
        errorResponse(409, "model_unavailable", `The model '${NANO}' is not available to your key.`),
      );
      render(<Chat />);

      send("hello");

      expect(await screen.findByRole("alert")).toHaveTextContent(NANO);
    });

    it.each([
      [
        "context_full",
        409,
        "This conversation is full",
        "Use /compact, choose a model with a larger context, or start a new conversation.",
      ],
      ["provider_request_refused", 422, null, "Nebius: messages must not be empty"],
      [
        "conversation_busy",
        409,
        "Still answering",
        "This conversation is still answering another message.",
      ],
    ])("%s shows its message", async (code, status, title, message) => {
      failWith(() => errorResponse(status, code, message));
      render(<Chat />);

      send("hello");

      const alert = await screen.findByRole("alert");
      if (title) expect(alert).toHaveTextContent(title);
      expect(alert).toHaveTextContent(message);
      expect(within(alert).queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
      expect(screen.getByText("hello")).toBeInTheDocument();
    });

    it.each([
      ["output_limit_reached", "The model ran out of room"],
      ["tool_loop_limit", "The answer could not be completed"],
    ])("%s keeps the text and offers to try again in place", async (code, title) => {
      const { calls } = fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "POST /api/chat": [
          () =>
            streamOf(
              conversationEvent("c2", "hello"),
              delta("A long answer"),
              errorEvent(code, "Out of room."),
            ),
          () => streamOf(delta("Short answer."), done),
        ],
      });
      render(<Chat />);

      send("hello");

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(title);
      expect(screen.getByText("A long answer")).toBeInTheDocument();

      fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));

      expect(await screen.findByText("Short answer.")).toBeInTheDocument();
      expect(screen.queryByText("A long answer")).not.toBeInTheDocument();
      expect(screen.getAllByText("hello")).toHaveLength(1);
      expect(chatBodies(calls)[1]).toMatchObject({ message: "hello", conversation_id: "c2" });
    });

    it("provider_rate_limited says to wait and offers to try again", async () => {
      failWith(() =>
        errorResponse(
          429,
          "provider_rate_limited",
          "Nebius is rate limiting requests. Wait and try again.",
        ),
      );
      render(<Chat />);

      send("hello");

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Wait and try again.");
      expect(within(alert).getByRole("button", { name: "Try again" })).toBeEnabled();
    });

    it("keeps using the conversation a refused first message was stored in", async () => {
      const { calls } = fakeApi({
        "GET /api/settings/models": json(200, loadout()),
        "POST /api/chat": [
          () =>
            errorResponse(409, "model_not_set", "No chat model is set.", {
              "X-Conversation-Id": "c5",
            }),
          () => streamOf(delta("Hi"), done),
        ],
      });
      render(<Chat />);

      send("hello");
      await screen.findByRole("alert");
      expect(window.location.pathname).toBe("/app/c5");
      send("hello");
      await screen.findByText("Hi");

      expect(chatBodies(calls)[1]).toEqual({ message: "hello", conversation_id: "c5" });
      // The server keeps one copy of a resent message, and so does the chat.
      const list = screen.getByRole("list", { name: "Conversation" });
      expect(within(list).getAllByText("hello")).toHaveLength(1);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("shows a resent message once after resuming a conversation where it got no answer", async () => {
      const { calls } = fakeApi({
        "GET /api/settings/models": json(200, withDefault),
        "GET /api/conversations/c1": json(
          200,
          conversation({ messages: [storedMessage(0, "user", "hello")] }),
        ),
        "POST /api/chat": () => streamOf(delta("Hi"), done),
      });
      render(<Chat conversationId="c1" />);
      await screen.findByText("hello");

      send("hello");
      await screen.findByText("Hi");

      const list = screen.getByRole("list", { name: "Conversation" });
      expect(within(list).getAllByText("hello")).toHaveLength(1);
      expect(chatBodies(calls)).toEqual([{ message: "hello", conversation_id: "c1" }]);
    });

    it("shows a message when the server cannot be reached", async () => {
      failWith(() => {
        throw new TypeError("Failed to fetch");
      });
      render(<Chat />);

      send("hello");

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The server could not be reached.",
      );
      expect(screen.getByLabelText("Message")).toBeEnabled();
    });

    it("sends a logged-out user to log in and back to the chat", async () => {
      failWith(() => errorResponse(401, "unauthenticated", "Log in to continue."));
      render(<Chat />);

      send("hello");

      await waitFor(() => expect(redirectToLogin).toHaveBeenCalledWith("/app"));
    });

    it("keeps the received text and says the answer was cut short when the connection breaks", async () => {
      const stream = openStream();
      failWith(() => stream.response);
      render(<Chat />);

      send("hello");
      await stream.push(delta("Half an ans"));
      await stream.fail();

      expect(await screen.findByText(/cut short/)).toBeInTheDocument();
      expect(screen.getByText("Half an ans")).toBeInTheDocument();
      expect(screen.getByLabelText("Message")).toBeEnabled();
    });
  });
});
