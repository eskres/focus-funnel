// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  delta,
  detail,
  done,
  fakeApi,
  json,
  loadout,
  source,
  storedMessage,
  streamOf,
  toolEvent,
  type WireSource,
} from "@/test/fake-api";

import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const OAT = source("t1", "Oat milk", "2026-08-02T09:00:00+00:00", ["groceries"]);
const LIST = source("t2", "Shopping list", "2026-09-20T09:00:00+00:00", ["groceries", "travel"]);
const LISBON = source("t3", "Lisbon trip", "2026-09-10T09:00:00+00:00", ["travel"]);
const STANDUP = source("t4", "Standup notes", "2026-09-01T09:00:00+00:00", ["work"]);

const searching = (...searches: WireSource[][]) => () =>
  streamOf(
    ...searches.flatMap((found) => [
      toolEvent("search_thoughts", "start"),
      toolEvent("search_thoughts", "end", "Searched your thoughts", found),
    ]),
    delta("Here is what you filed."),
    done,
  );

function api(routes: Parameters<typeof fakeApi>[0]) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/conversations/c1": json(200, detail()),
    ...routes,
  });
}

async function ask(text = "what did I say about milk?") {
  render(<Chat conversationId="c1" />);
  await screen.findByLabelText("Message");
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  return screen.findByRole("region", { name: "Sources" });
}

function titles(list: HTMLElement): string[] {
  return within(list).getAllByRole("link").map((link) => link.textContent ?? "");
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("sources under an answer", () => {
  it("lists the search's thoughts in its order, with date and tags, each linking to the thought", async () => {
    api({ "POST /api/chat": searching([OAT, LIST]) });

    const list = await ask();

    expect(titles(list)).toEqual(["Oat milk", "Shopping list"]);
    const first = within(list).getAllByRole("listitem")[0];
    expect(first).toHaveTextContent("2026-08-02");
    expect(first).toHaveTextContent("#groceries");
    expect(within(list).getByRole("link", { name: "Oat milk" })).toHaveAttribute("href", "?thought=t1");
  });

  it("lists a thought found by two searches once", async () => {
    api({ "POST /api/chat": searching([OAT], [LIST, OAT]) });

    expect(titles(await ask())).toEqual(["Oat milk", "Shopping list"]);
  });

  it("shows no list when the searches found nothing", async () => {
    api({ "POST /api/chat": searching([]) });
    render(<Chat conversationId="c1" />);
    await screen.findByLabelText("Message");
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "the boat?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByText("Here is what you filed.");
    expect(screen.queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("sorts newest first and back, with no request", async () => {
    const { calls } = api({ "POST /api/chat": searching([OAT, LIST, LISBON]) });
    const list = await ask();
    const before = calls.length;

    const toggle = within(list).getByRole("button", { name: "Newest first" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(titles(list)).toEqual(["Shopping list", "Lisbon trip", "Oat milk"]);

    fireEvent.click(toggle);
    expect(titles(list)).toEqual(["Oat milk", "Shopping list", "Lisbon trip"]);
    expect(calls).toHaveLength(before);
  });

  it("filters by any picked tag, and clears, with no request", async () => {
    const { calls } = api({ "POST /api/chat": searching([OAT, LISBON, STANDUP]) });
    const list = await ask();
    const before = calls.length;
    const tags = within(list).getByRole("group", { name: "Filter by tag" });

    fireEvent.click(within(tags).getByRole("button", { name: "#travel" }));
    expect(titles(list)).toEqual(["Lisbon trip"]);

    fireEvent.click(within(tags).getByRole("button", { name: "#work" }));
    expect(titles(list)).toEqual(["Lisbon trip", "Standup notes"]);

    fireEvent.click(within(tags).getByRole("button", { name: "Clear" }));
    expect(titles(list)).toEqual(["Oat milk", "Lisbon trip", "Standup notes"]);
    expect(calls).toHaveLength(before);
    expect(screen.getByText("Here is what you filed.")).toBeInTheDocument();
  });

  it("shows each answer's sources again when the conversation is reopened", async () => {
    const call = (id: string) => ({
      tool_calls: [{ id, type: "function", function: { name: "search_thoughts", arguments: "{}" } }],
    });
    api({
      "GET /api/conversations/c1": json(
        200,
        detail({
          messages: [
            storedMessage(0, "user", "/pull milk"),
            storedMessage(1, "assistant", null, call("a")),
            storedMessage(2, "tool", "2 match", { tool_call_id: "a", details: { sources: [OAT, LIST] } }),
            storedMessage(3, "assistant", "You filed two."),
            storedMessage(4, "user", "/pull the boat"),
            storedMessage(5, "assistant", null, call("b")),
            storedMessage(6, "tool", "No match", { tool_call_id: "b", details: { sources: [] } }),
            storedMessage(7, "assistant", "Nothing filed matched."),
            storedMessage(8, "user", "and Lisbon?"),
            storedMessage(9, "assistant", null, call("c")),
            storedMessage(10, "tool", "1 match", { tool_call_id: "c", details: { sources: [LISBON] } }),
            storedMessage(11, "assistant", "One trip."),
          ],
        }),
      ),
    });
    render(<Chat conversationId="c1" />);

    const first = (await screen.findByText("You filed two.")).closest("li")!;
    const empty = screen.getByText("Nothing filed matched.").closest("li")!;
    const last = screen.getByText("One trip.").closest("li")!;
    await waitFor(() =>
      expect(titles(within(first).getByRole("region", { name: "Sources" }))).toEqual([
        "Oat milk",
        "Shopping list",
      ]),
    );
    expect(within(empty).queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
    expect(titles(within(last).getByRole("region", { name: "Sources" }))).toEqual(["Lisbon trip"]);
  });
});
