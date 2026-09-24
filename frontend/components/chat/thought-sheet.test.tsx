// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  delta,
  detail,
  done,
  errorResponse,
  fakeApi,
  json,
  loadout,
  source,
  streamOf,
  toolEvent,
} from "@/test/fake-api";

import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const THOUGHT = {
  id: "t1",
  title: "Oat milk",
  summary: "Buy oat milk on the way home.",
  tags: ["groceries", "errands"],
  category: "task",
  raw_text: "buy oat milk, the barista one",
  created_at: "2026-09-20T08:00:00Z",
  updated_at: "2026-09-21T08:00:00Z",
};

function api(routes: Parameters<typeof fakeApi>[0]) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/conversations/c1": json(200, detail()),
    ...routes,
  });
}

function at(address: string) {
  window.history.replaceState(null, "", address);
}

async function sheet() {
  return screen.findByRole("dialog");
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  at("/");
});

describe("the thought sheet", () => {
  it("opens the thought the address names, with every field and no way to change it", async () => {
    at("/app/c1?thought=t1");
    api({ "GET /api/thoughts/t1": json(200, THOUGHT) });

    render(<Chat conversationId="c1" />);

    const dialog = await sheet();
    expect(await within(dialog).findByText("Oat milk")).toBeInTheDocument();
    expect(within(dialog).getByText("Buy oat milk on the way home.")).toBeInTheDocument();
    expect(within(dialog).getByText("buy oat milk, the barista one")).toBeInTheDocument();
    expect(within(dialog).getByText("task")).toBeInTheDocument();
    expect(within(dialog).getByText("#groceries")).toBeInTheDocument();
    expect(within(dialog).getByText("#errands")).toBeInTheDocument();
    expect(within(dialog).getByText(/^Filed .* · changed /)).toBeInTheDocument();
    const buttons = within(dialog).getAllByRole("button").map((b) => b.textContent);
    expect(buttons).toEqual(["Close"]);
    expect(dialog.textContent?.toLowerCase()).not.toMatch(/edit|delete/);
  });

  it.each([
    ["empty", null],
    ["the same as the summary", "Buy oat milk on the way home."],
  ])("hides the raw text when it is %s", async (_case, rawText) => {
    at("/app/c1?thought=t1");
    api({ "GET /api/thoughts/t1": json(200, { ...THOUGHT, raw_text: rawText }) });

    render(<Chat conversationId="c1" />);

    const dialog = await sheet();
    await within(dialog).findByText("Oat milk");
    expect(within(dialog).queryByRole("region", { name: "Raw text" })).not.toBeInTheDocument();
    expect(within(dialog).getAllByText("Buy oat milk on the way home.")).toHaveLength(1);
  });

  it("says the thought no longer exists on a 404, and shows nothing of it", async () => {
    at("/app/c1?thought=gone");
    api({ "GET /api/thoughts/gone": errorResponse(404, "not_found", "No such thought.") });

    render(<Chat conversationId="c1" />);

    const dialog = await sheet();
    expect(await within(dialog).findByText("This thought no longer exists.")).toBeInTheDocument();
    expect(within(dialog).queryByRole("region", { name: "Summary" })).not.toBeInTheDocument();
  });

  it("opens from a source, and closing keeps the chat and the unsent text", async () => {
    at("/app/c1");
    api({
      "GET /api/thoughts/t1": json(200, THOUGHT),
      "POST /api/chat": () =>
        streamOf(
          toolEvent("search_thoughts", "start"),
          toolEvent("search_thoughts", "end", "Searched", [
            source("t1", "Oat milk", "2026-09-20T08:00:00+00:00", ["groceries"]),
          ]),
          delta("You filed oat milk."),
          done,
        ),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByLabelText("Message");
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "what about milk?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const sources = await screen.findByRole("region", { name: "Sources" });
    await waitFor(() => expect(screen.getByLabelText("Message")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "half-written" } });

    fireEvent.click(within(sources).getByRole("link", { name: "Oat milk" }));

    const dialog = await sheet();
    expect(window.location.pathname + window.location.search).toBe("/app/c1?thought=t1");
    await within(dialog).findByText("Buy oat milk on the way home.");

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(window.location.pathname + window.location.search).toBe("/app/c1");
    expect(screen.getByText("You filed oat milk.")).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("half-written");
  });

  it("closes on Back", async () => {
    at("/app/c1");
    api({ "GET /api/thoughts/t1": json(200, THOUGHT) });
    render(<Chat conversationId="c1" />);
    await screen.findByLabelText("Message");
    const { openThought } = await import("@/lib/thought-link");

    openThought("t1");
    await sheet();
    window.history.back();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(window.location.search).toBe("");
  });
});
