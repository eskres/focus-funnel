// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  detail,
  fakeApi,
  json,
  loadout,
  source,
  storedMessage,
  wireProposal,
  type WirePart,
} from "@/test/fake-api";

import { CategoriesProvider } from "./categories-context";
import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => window.location.pathname,
}));

const TRIP: WirePart = { title: "Trip ideas", summary: "Go to Lisbon.", tags: ["travel"], category: "idea" };
const EGGS: WirePart = { title: "Eggs", summary: "Buy eggs.", tags: ["groceries"], category: "task" };

const THOUGHT = {
  id: "t1",
  title: "Trip ideas",
  summary: "Go to Lisbon.",
  tags: ["travel"],
  category: "idea",
  raw_text: null,
  created_at: "2026-09-20T08:00:00Z",
  updated_at: "2026-09-20T08:00:00Z",
  origin: null,
};

const searchCall = (id: string) => ({
  tool_calls: [{ id, type: "function", function: { name: "search_thoughts", arguments: "{}" } }],
});
const proposeCall = (id: string) => ({
  tool_calls: [{ id, type: "function", function: { name: "propose_thought", arguments: "{}" } }],
});

/** A conversation with a saved card for t1, and an answer whose sources list t1. */
const stored = (parts: WirePart[] = [{ ...TRIP, thought_id: "t1", saved_title: "Trip ideas" }]) =>
  detail({
    messages: [
      storedMessage(0, "user", "/push Lisbon"),
      storedMessage(1, "assistant", null, proposeCall("a")),
      storedMessage(2, "tool", "shown", { tool_call_id: "a", details: { proposal_id: "p1" } }),
      storedMessage(3, "assistant", "Want to keep it?"),
      storedMessage(4, "user", "/pull trips"),
      storedMessage(5, "assistant", null, searchCall("b")),
      storedMessage(6, "tool", "1 match", {
        tool_call_id: "b",
        details: { sources: [source("t1", "Trip ideas", "2026-09-20T08:00:00+00:00", ["travel"])] },
      }),
      storedMessage(7, "assistant", "You filed one trip."),
    ],
    proposals: [wireProposal("p1", parts)],
  });

function api(routes: Parameters<typeof fakeApi>[0] = {}) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/settings/categories": json(200, { fixed: ["task", "idea"], added: [] }),
    "GET /api/conversations/c1": json(200, stored()),
    "GET /api/thoughts/t1": json(200, THOUGHT),
    ...routes,
  });
}

async function openChat() {
  window.history.replaceState(null, "", "/app/c1");
  render(
    <CategoriesProvider>
      <Chat conversationId="c1" />
    </CategoriesProvider>,
  );
  await screen.findByLabelText("Message");
}

/** The sources list under the answer, as link texts and the text of each row. */
async function sourcesOf() {
  const answer = (await screen.findByText("You filed one trip.")).closest("li")!;
  const list = await within(answer).findByRole("region", { name: "Sources" });
  return {
    links: within(list).getAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")]),
    text: list.textContent,
  };
}

async function openSaved(title: string) {
  const saved = await screen.findByRole("group", { name: `Saved: ${title}` });
  fireEvent.click(within(saved).getByRole("link", { name: "Open" }));
  const sheet = await screen.findByRole("dialog", { name: THOUGHT.title });
  await within(sheet).findByRole("button", { name: "Edit" });
  return sheet;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("a saved card in the open chat", () => {
  it("shows a new title from the sheet at once, and the sources list stays as it was", async () => {
    api({ "PATCH /api/thoughts/t1": json(200, { ...THOUGHT, title: "Lisbon trip" }) });
    await openChat();
    const before = await sourcesOf();
    const sheet = await openSaved("Trip ideas");

    fireEvent.click(within(sheet).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(sheet).getByLabelText("Title"), { target: { value: "Lisbon trip" } });
    fireEvent.click(within(sheet).getByRole("button", { name: "Save" }));

    const card = await screen.findByRole("group", { name: "Saved: Lisbon trip" });
    expect(within(card).getByRole("link", { name: "Open" })).toHaveAttribute("href", "?thought=t1");
    expect(screen.queryByRole("group", { name: "Saved: Trip ideas" })).not.toBeInTheDocument();
    expect(await sourcesOf()).toEqual(before);
    expect(before.links).toEqual([["Trip ideas", "?thought=t1"]]);
  });

  it("turns to Deleted with no link at once after a delete, and the sources list stays as it was", async () => {
    api({ "DELETE /api/thoughts/t1": new Response(null, { status: 204 }) });
    await openChat();
    const before = await sourcesOf();
    const sheet = await openSaved("Trip ideas");

    fireEvent.click(within(sheet).getByRole("button", { name: "Delete" }));
    const ask = await screen.findByRole("dialog", { name: "Delete this thought?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Delete" }));

    const card = await screen.findByRole("group", { name: "Deleted: Trip ideas" });
    expect(within(card).getByRole("status")).toHaveTextContent("Deleted:");
    expect(within(card).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /^Saved:/ })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await sourcesOf()).toEqual(before);
  });

  it("keeps a renamed card's title after an edit that sends no title", async () => {
    const renamed = { ...THOUGHT, title: "Lisbon trip" };
    const { calls } = api({
      "GET /api/conversations/c1": json(
        200,
        stored([{ ...TRIP, thought_id: "t1", saved_title: "Lisbon trip", deleted: false }]),
      ),
      "GET /api/thoughts/t1": json(200, renamed),
      "PATCH /api/thoughts/t1": json(200, { ...renamed, tags: ["travel", "spring"] }),
    });
    await openChat();
    const saved = await screen.findByRole("group", { name: "Saved: Lisbon trip" });
    fireEvent.click(within(saved).getByRole("link", { name: "Open" }));
    const sheet = await screen.findByRole("dialog", { name: "Lisbon trip" });

    fireEvent.click(await within(sheet).findByRole("button", { name: "Edit" }));
    fireEvent.change(within(sheet).getByLabelText(/Tags/), { target: { value: "travel, spring" } });
    fireEvent.click(within(sheet).getByRole("button", { name: "Save" }));

    expect(await within(sheet).findByText("#spring")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PATCH")).toEqual([
      { method: "PATCH", path: "/api/thoughts/t1", body: { tags: ["travel", "spring"] } },
    ]);
    expect(screen.getByRole("group", { name: "Saved: Lisbon trip" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Saved: Trip ideas" })).not.toBeInTheDocument();
  });

  it("does not change for another thought's edit", async () => {
    const { updateThought } = await import("@/lib/thoughts");
    api({ "PATCH /api/thoughts/t9": json(200, { ...THOUGHT, id: "t9", title: "Something else" }) });
    await openChat();
    await screen.findByRole("group", { name: "Saved: Trip ideas" });

    await updateThought("t9", { title: "Something else" });

    expect(screen.getByRole("group", { name: "Saved: Trip ideas" })).toBeInTheDocument();
  });
});

describe("a reopened conversation", () => {
  it("shows a saved card's current title with its link, and a deleted one as Deleted with no link", async () => {
    api({
      "GET /api/conversations/c1": json(
        200,
        stored([
          { ...TRIP, thought_id: "t1", saved_title: "Lisbon trip", deleted: false },
          { ...EGGS, thought_id: "t2", saved_title: null, deleted: true },
        ]),
      ),
    });
    await openChat();

    const saved = await screen.findByRole("group", { name: "Saved: Lisbon trip" });
    expect(within(saved).getByRole("link", { name: "Open" })).toHaveAttribute("href", "?thought=t1");
    const deleted = screen.getByRole("group", { name: "Deleted: Eggs" });
    expect(within(deleted).queryByRole("link")).not.toBeInTheDocument();
    // Both parts are filed: there is nothing to confirm or merge.
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Merge into one" })).not.toBeInTheDocument();
    // The sources list keeps the title the search returned.
    expect((await sourcesOf()).links).toEqual([["Trip ideas", "?thought=t1"]]);
  });

  it("shows merged parts saved as one deleted thought as one Deleted card", async () => {
    api({
      "GET /api/conversations/c1": json(
        200,
        stored([
          { ...TRIP, thought_id: "t1", saved_title: null, deleted: true },
          { ...EGGS, thought_id: "t1", saved_title: null, deleted: true },
        ]),
      ),
    });
    await openChat();

    expect(await screen.findByRole("group", { name: "Deleted: Trip ideas" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Eggs/ })).not.toBeInTheDocument();
  });
});
