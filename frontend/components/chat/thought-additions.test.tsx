// @vitest-environment jsdom
// The additions list and "Undo last addition" in the thought sheet
// (thought-appending, thought-detail-view spec).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { THOUGHT_CHANGED_EVENT, type ThoughtChanged } from "@/lib/thoughts";
import { detail, fakeApi, json, loadout } from "@/test/fake-api";

import { Chat } from "./chat";

const push = vi.hoisted(() => vi.fn());
vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => window.location.pathname,
}));

const ORIGIN = {
  conversation_id: "c0",
  conversation_title: "Bike plans",
  archived: false,
  proposal_id: "p0",
  proposed_at: "2025-09-20T08:00:00Z",
};

const NEWER = {
  id: "a2",
  added_at: "2026-10-02T09:30:00Z",
  undone: false,
  conversation_id: "c2",
  conversation_title: "Lock prices",
  proposal_id: "p2",
};

const OLDER = {
  id: "a1",
  added_at: "2026-09-26T18:00:00Z",
  undone: false,
  conversation_id: "c1",
  conversation_title: "Lock colours",
  proposal_id: "p1",
};

const THOUGHT = {
  id: "t1",
  title: "Buy new bike lock",
  summary: "Buy a black folding lock, under 80 euros.",
  tags: ["bike", "price"],
  category: "task",
  raw_text: null,
  created_at: "2025-09-20T08:00:00Z",
  updated_at: "2026-10-02T09:30:00.123456Z",
  origin: ORIGIN,
  additions: [NEWER, OLDER],
};

const RESTORED = {
  ...THOUGHT,
  summary: "Buy a black lock.",
  tags: ["bike"],
  updated_at: "2026-10-03T10:00:00.5Z",
  additions: [{ ...NEWER, undone: true }, OLDER],
};

const UNDO = "POST /api/thoughts/t1/additions/a2/undo";

function api(routes: Parameters<typeof fakeApi>[0] = {}) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/conversations/c1": json(200, detail()),
    "GET /api/thoughts/t1": json(200, THOUGHT),
    ...routes,
  });
}

function at(address: string) {
  window.history.replaceState(null, "", address);
}

async function sheet() {
  const dialog = await screen.findByRole("dialog", { name: "Buy new bike lock" });
  await within(dialog).findByText(/^Buy a black/);
  return dialog;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  at("/");
});

describe("the additions in the thought sheet", () => {
  it("lists them newest first, with dates and conversation titles linked to their cards", async () => {
    at("/app/c1?thought=t1");
    api();
    render(<Chat conversationId="c1" />);

    const additions = within(await sheet()).getByRole("region", { name: "Additions" });

    const items = within(additions).getAllByRole("listitem");
    expect(items.map((item) => within(item).getByRole("link").textContent)).toEqual([
      "Lock prices",
      "Lock colours",
    ]);
    expect(within(items[0]).getByRole("link")).toHaveAttribute("href", "/app/c2?proposal=p2");
    expect(within(items[1]).getByRole("link")).toHaveAttribute("href", "/app/c1?proposal=p1");
    expect(within(items[0]).getByText(/^added .*2026/)).toBeInTheDocument();
    expect(within(items[1]).getByText(/^added .*2026/)).toBeInTheDocument();
    // The origin is still where the thought was first filed.
    const origin = screen.getByRole("region", { name: "Origin" });
    expect(within(origin).getByRole("link", { name: "Bike plans" })).toHaveAttribute(
      "href",
      "/app/c0?proposal=p0",
    );
  });

  it.each([
    ["empty", []],
    ["missing", undefined],
  ])("is absent when the additions are %s, with no undo", async (_case, additions) => {
    at("/app/c1?thought=t1");
    api({ "GET /api/thoughts/t1": json(200, { ...THOUGHT, additions }) });
    render(<Chat conversationId="c1" />);

    const dialog = await sheet();

    expect(within(dialog).queryByRole("region", { name: "Additions" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Undo last addition" })).not.toBeInTheDocument();
  });

  it("opens another conversation at the addition's card", async () => {
    at("/app/c1?thought=t1");
    api();
    render(<Chat conversationId="c1" />);
    const additions = within(await sheet()).getByRole("region", { name: "Additions" });

    fireEvent.click(within(additions).getByRole("link", { name: "Lock prices" }));

    expect(push).toHaveBeenCalledWith("/app/c2?proposal=p2");
  });

  it("in the open conversation, closes the sheet and names the card in the address", async () => {
    at("/app/c1?thought=t1");
    api();
    render(<Chat conversationId="c1" />);
    const additions = within(await sheet()).getByRole("region", { name: "Additions" });

    fireEvent.click(within(additions).getByRole("link", { name: "Lock colours" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(window.location.pathname + window.location.search).toBe("/app/c1?proposal=p1");
    expect(push).not.toHaveBeenCalled();
  });

  it("asks before undoing, then shows the restored fields and tells the card", async () => {
    at("/app/c1?thought=t1");
    const { calls } = api({ [UNDO]: json(200, RESTORED) });
    const changes: ThoughtChanged[] = [];
    const listen = (event: Event) => changes.push((event as CustomEvent<ThoughtChanged>).detail);
    window.addEventListener(THOUGHT_CHANGED_EVENT, listen);
    render(<Chat conversationId="c1" />);
    const dialog = await sheet();

    fireEvent.click(within(dialog).getByRole("button", { name: "Undo last addition" }));
    const ask = await screen.findByRole("dialog", { name: "Undo the last addition?" });
    expect(ask).toHaveTextContent("before the addition from “Lock prices”");
    fireEvent.click(within(ask).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Undo the last addition?" })).not.toBeInTheDocument(),
    );
    expect(calls.filter((call) => call.method === "POST")).toEqual([]);

    fireEvent.click(within(dialog).getByRole("button", { name: "Undo last addition" }));
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "Undo the last addition?" })).getByRole("button", {
        name: "Undo",
      }),
    );

    expect(await within(dialog).findByText("Buy a black lock.")).toBeInTheDocument();
    expect(within(dialog).queryByText("#price")).not.toBeInTheDocument();
    expect(within(dialog).getByText("#bike")).toBeInTheDocument();
    expect(calls.filter((call) => call.method === "POST").map((call) => call.path)).toEqual([
      "/api/thoughts/t1/additions/a2/undo",
    ]);
    // The newest addition is undone now, so there is nothing more to undo.
    expect(within(dialog).queryByRole("button", { name: "Undo last addition" })).not.toBeInTheDocument();
    const first = within(within(dialog).getByRole("region", { name: "Additions" })).getAllByRole("listitem")[0];
    expect(within(first).getByText("Undone")).toBeInTheDocument();
    expect(changes).toEqual([{ id: "t1", title: "Buy new bike lock", undone: "p2" }]);
    window.removeEventListener(THOUGHT_CHANGED_EVENT, listen);
  });

  it("shows a dated thought's date with its additions, and keeps it after an undo (thought-dates)", async () => {
    const when = { start: "2026-10-02T19:00", end: null, time_zone: "UTC" };
    at("/app/c1?thought=t1");
    api({
      "GET /api/thoughts/t1": json(200, { ...THOUGHT, when }),
      [UNDO]: json(200, { ...RESTORED, when }),
    });
    render(<Chat conversationId="c1" />);
    const dialog = await sheet();

    expect(within(dialog).getByText(/^When: /)).toHaveTextContent(/2026/);
    expect(within(dialog).getByRole("region", { name: "Additions" })).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Undo last addition" }));
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "Undo the last addition?" })).getByRole("button", {
        name: "Undo",
      }),
    );

    expect(await within(dialog).findByText("Buy a black lock.")).toBeInTheDocument();
    expect(within(dialog).getByText(/^When: /)).toHaveTextContent(/2026/);

    // Editing shows the date fields beside the additions list.
    fireEvent.click(within(dialog).getByRole("button", { name: "Edit" }));
    expect(within(dialog).getByRole("region", { name: "Additions" })).toBeInTheDocument();
    const editing = within(dialog).getByRole("region", { name: "Edit thought" });
    expect(within(editing).getByLabelText("Start date")).toHaveValue("2026-10-02");
    expect(within(editing).getByLabelText("Start time")).toHaveValue("19:00");
  });

  it("says why when the undo is refused because the thought changed, and changes nothing", async () => {
    at("/app/c1?thought=t1");
    api({
      [UNDO]: json(409, {
        error: {
          code: "thought_changed",
          message: "The thought changed after this addition, so it can no longer be undone.",
          thought: { id: "t1", title: "Bike lock", summary: THOUGHT.summary, tags: THOUGHT.tags, category: "task", updated_at: "x" },
        },
      }),
    });
    render(<Chat conversationId="c1" />);
    const dialog = await sheet();

    fireEvent.click(within(dialog).getByRole("button", { name: "Undo last addition" }));
    const ask = await screen.findByRole("dialog", { name: "Undo the last addition?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Undo" }));

    expect(await within(ask).findByRole("alert")).toHaveTextContent(
      "The thought changed after this addition, so it can no longer be undone.",
    );
    expect(within(dialog).getByText(THOUGHT.summary)).toBeInTheDocument();
    expect(within(dialog).getByText("#price")).toBeInTheDocument();
  });

  it("offers no undo when the newest addition is already undone", async () => {
    at("/app/c1?thought=t1");
    api({ "GET /api/thoughts/t1": json(200, { ...THOUGHT, additions: [{ ...NEWER, undone: true }, OLDER] }) });
    render(<Chat conversationId="c1" />);

    const dialog = await sheet();

    expect(within(dialog).getByRole("region", { name: "Additions" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Undo last addition" })).not.toBeInTheDocument();
  });
});
