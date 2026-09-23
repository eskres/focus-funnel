// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { redirectToLogin } from "@/lib/redirect-to-login";

import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));

const encoder = new TextEncoder();

const delta = (text: string) => `event: delta\ndata: ${JSON.stringify({ text })}\n\n`;
const done = "event: done\ndata: {}\n\n";
const errorEvent = (code: string, message: string) =>
  `event: error\ndata: ${JSON.stringify({ error: { code, message } })}\n\n`;

/** A response whose body the test feeds one part at a time. */
function openStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }),
    push: (text: string) => act(async () => controller.enqueue(encoder.encode(text))),
    close: () => act(async () => controller.close()),
    fail: () => act(async () => controller.error(new TypeError("network error"))),
  };
}

const errorResponse = (status: number, code: string, message: string) =>
  Response.json({ error: { code, message } }, { status });

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function send(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

describe("Chat", () => {
  it("lists the commands on a chat with no messages", () => {
    render(<Chat />);

    for (const command of ["/push", "/pull", "/explore"]) {
      expect(screen.getByText(command, { selector: "code" })).toBeInTheDocument();
    }
    expect(screen.getByText("Propose a thought to file")).toBeInTheDocument();
  });

  it("adds the user's message to the conversation and clears the input", async () => {
    const stream = openStream();
    fetchMock.mockResolvedValue(stream.response);
    render(<Chat />);

    send("/push buy milk");

    const conversation = await screen.findByRole("list", { name: "Conversation" });
    expect(within(conversation).getByText("/push buy milk")).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("");
    expect(screen.queryByText("Propose a thought to file")).not.toBeInTheDocument();

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/chat");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ message: "/push buy milk" });
    expect(new Headers(init.headers).get("Accept")).toBe("text/event-stream");
    await stream.close();
  });

  it.each(["", "   ", "\n\t "])("sends nothing for the message %j", (text) => {
    render(<Chat />);

    send(text);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("list", { name: "Conversation" })).not.toBeInTheDocument();
    expect(screen.getByText("Propose a thought to file")).toBeInTheDocument();
  });

  it("sends on Enter and adds a line on Shift+Enter", async () => {
    const stream = openStream();
    fetchMock.mockResolvedValue(stream.response);
    render(<Chat />);
    const input = screen.getByLabelText("Message");
    fireEvent.change(input, { target: { value: "hello" } });

    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await stream.close();
  });

  it("disables the composer while an answer is arriving and enables it after", async () => {
    const stream = openStream();
    fetchMock.mockResolvedValue(stream.response);
    render(<Chat />);

    send("hello");

    await waitFor(() => expect(screen.getByLabelText("Message")).toBeDisabled());
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    await stream.push(delta("Hi") + done);
    await stream.close();

    await waitFor(() => expect(screen.getByLabelText("Message")).toBeEnabled());
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("re-enables the composer after an error", async () => {
    fetchMock.mockResolvedValue(errorResponse(500, "internal_error", "Something went wrong."));
    render(<Chat />);

    send("/push x");

    await screen.findByRole("alert");
    expect(screen.getByLabelText("Message")).toBeEnabled();
  });

  it("shows partial text before the answer completes, then stops showing progress", async () => {
    const stream = openStream();
    fetchMock.mockResolvedValue(stream.response);
    render(<Chat />);

    send("what did I file?");
    await stream.push(delta("You filed "));

    expect(await screen.findByText("You filed")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Writing");

    await stream.push(delta("milk."));
    expect(await screen.findByText("You filed milk.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();

    await stream.push(done);
    await stream.close();
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(screen.getByText("You filed milk.")).toBeInTheDocument();
  });

  describe("errors", () => {
    it.each([
      ["provider_key_missing", 409, "No API key saved", "Go to provider settings", "/settings"],
      [
        "provider_key_rejected",
        409,
        "Your API key no longer works",
        "Go to provider settings",
        "/settings",
      ],
    ])("%s links to the provider settings", async (code, status, title, link, href) => {
      fetchMock.mockResolvedValue(errorResponse(status, code, "Key problem."));
      render(<Chat />);

      send("/push x");

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(title);
      expect(within(alert).getByRole("link", { name: link })).toHaveAttribute("href", href);
      expect(screen.getByText("/push x")).toBeInTheDocument();
    });

    it("shows other errors with the backend message and keeps the user's message", async () => {
      fetchMock.mockResolvedValue(errorResponse(500, "internal_error", "Something went wrong."));
      render(<Chat />);

      send("/push x");

      expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
      expect(screen.getByText("/push x")).toBeInTheDocument();
    });

    it("shows a message when the server cannot be reached", async () => {
      fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
      render(<Chat />);

      send("/push x");

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The server could not be reached.",
      );
      expect(screen.getByText("/push x")).toBeInTheDocument();
      expect(screen.getByLabelText("Message")).toBeEnabled();
    });

    it("shows an error event that arrives mid-stream the same way, and keeps the text", async () => {
      const stream = openStream();
      fetchMock.mockResolvedValue(stream.response);
      render(<Chat />);

      send("/pull x");
      await stream.push(
        delta("Partial") +
          errorEvent("provider_key_rejected", "Nebius rejected the key."),
      );
      await stream.close();

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Your API key no longer works");
      expect(within(alert).getByRole("link", { name: "Go to provider settings" })).toBeInTheDocument();
      expect(screen.getByText("Partial")).toBeInTheDocument();
      expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
    });

    it("sends a logged-out user to log in and back to the chat", async () => {
      fetchMock.mockResolvedValue(errorResponse(401, "unauthenticated", "Log in to continue."));
      render(<Chat />);

      send("/push x");

      await waitFor(() => expect(redirectToLogin).toHaveBeenCalledWith("/app"));
    });
  });

  describe("a stream that stops early", () => {
    it("keeps the received text and says the answer was cut short when the connection breaks", async () => {
      const stream = openStream();
      fetchMock.mockResolvedValue(stream.response);
      render(<Chat />);

      send("/explore x");
      await stream.push(delta("Half an ans"));
      await stream.fail();

      expect(await screen.findByText(/cut short/)).toBeInTheDocument();
      expect(screen.getByText("Half an ans")).toBeInTheDocument();
        expect(screen.queryByRole("status")).not.toBeInTheDocument();
      expect(screen.getByLabelText("Message")).toBeEnabled();
    });

    it("treats a stream that closes without done as cut short", async () => {
      const stream = openStream();
      fetchMock.mockResolvedValue(stream.response);
      render(<Chat />);

      send("/explore x");
      await stream.push(delta("Half an ans"));
      await stream.close();

      expect(await screen.findByText(/cut short/)).toBeInTheDocument();
      expect(screen.getByText("Half an ans")).toBeInTheDocument();
    });

    it("sends the same message again from a cut-short answer", async () => {
      const first = openStream();
      const second = openStream();
      fetchMock.mockResolvedValueOnce(first.response).mockResolvedValueOnce(second.response);
      render(<Chat />);

      send("/explore x");
      await first.push(delta("Half"));
      await first.fail();
      fireEvent.click(await screen.findByRole("button", { name: "Send again" }));

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
      expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ message: "/explore x" });
      await second.push(delta("Whole answer") + done);
      await second.close();
      expect(await screen.findByText("Whole answer")).toBeInTheDocument();
      expect(screen.getByText("Half")).toBeInTheDocument();
    });
  });
});
