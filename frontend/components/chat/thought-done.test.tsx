// @vitest-environment jsdom
// The sheet's Done box (thought-status design decision 13).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { detail, errorResponse, fakeApi, json, loadout } from "@/test/fake-api";

import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => window.location.pathname,
}));

const CHANGED = "2026-09-21T08:00:00Z";
const DONE_AT = "2026-09-23T09:30:00Z";

const OPEN = {
  id: "t1",
  title: "Call the plumber",
  summary: "Ask about the leak under the sink.",
  tags: ["home"],
  category: "task",
  raw_text: null,
  created_at: "2026-09-20T08:00:00Z",
  updated_at: CHANGED,
  status: "open",
  status_changed_at: null,
};

const DONE = { ...OPEN, status: "done", status_changed_at: DONE_AT };

/** As the sheet stamps a moment. */
function stamp(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function api(routes: Parameters<typeof fakeApi>[0]) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/conversations/c1": json(200, detail()),
    ...routes,
  });
}

async function openSheet() {
  window.history.replaceState(null, "", "/app/c1?thought=t1");
  render(<Chat conversationId="c1" />);
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText("Ask about the leak under the sink.");
  return dialog;
}

function deferred() {
  let resolve: (response: Response) => void = () => undefined;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("the Done box in the thought sheet", () => {
  it("is checked for a done thought and shows the date it was marked done", async () => {
    api({ "GET /api/thoughts/t1": json(200, DONE) });
    const dialog = await openSheet();

    expect(within(dialog).getByRole("checkbox", { name: "Done" })).toBeChecked();
    expect(within(dialog).getByText(`Done on ${stamp(DONE_AT)}`)).toBeInTheDocument();
  });

  it("is unchecked for an open thought, with no done date", async () => {
    api({ "GET /api/thoughts/t1": json(200, OPEN) });
    const dialog = await openSheet();

    expect(within(dialog).getByRole("checkbox", { name: "Done" })).not.toBeChecked();
    expect(within(dialog).queryByText(/^Done on /)).not.toBeInTheDocument();
  });

  it("reads a thought from an older server, with no status, as open", async () => {
    const older: Record<string, unknown> = { ...OPEN };
    delete older.status;
    delete older.status_changed_at;
    api({ "GET /api/thoughts/t1": json(200, older) });
    const dialog = await openSheet();

    expect(within(dialog).getByRole("checkbox", { name: "Done" })).not.toBeChecked();
  });

  it("sends no PATCH and no undo when the sheet is opened and closed without Edit, Delete, Done, or Undo", async () => {
    const withAddition = {
      ...DONE,
      additions: [
        {
          id: "a1",
          added_at: "2026-09-22T08:00:00Z",
          undone: false,
          conversation_id: "c2",
          conversation_title: "Leak",
          proposal_id: "p2",
        },
      ],
    };
    const { calls } = api({ "GET /api/thoughts/t1": json(200, withAddition) });
    const dialog = await openSheet();
    expect(within(dialog).getByRole("button", { name: "Undo last addition" })).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls.filter((call) => call.method !== "GET")).toEqual([]);
  });

  it("sends one PATCH with only status, is disabled while it runs, then shows the answer with the same changed date", async () => {
    const patch = deferred();
    const { calls } = api({
      "GET /api/thoughts/t1": json(200, OPEN),
      "PATCH /api/thoughts/t1": () => patch.promise,
    });
    const dialog = await openSheet();
    const header = within(dialog).getByText(/^Filed .* · changed /).textContent;
    expect(header).toContain(`changed ${stamp(CHANGED)}`);
    const box = within(dialog).getByRole("checkbox", { name: "Done" });

    fireEvent.click(box);

    await waitFor(() => expect(box).toBeDisabled());
    expect(box).toBeChecked();
    patch.resolve(json(200, DONE));

    await waitFor(() => expect(box).toBeEnabled());
    expect(box).toBeChecked();
    expect(within(dialog).getByText(`Done on ${stamp(DONE_AT)}`)).toBeInTheDocument();
    expect(within(dialog).getByText(/^Filed .* · changed /).textContent).toBe(header);
    const patches = calls.filter((call) => call.method === "PATCH");
    expect(patches).toEqual([{ method: "PATCH", path: "/api/thoughts/t1", body: { status: "done" } }]);
  });

  it("turns Edit, Delete, and Undo off while its PATCH runs, so no other change runs beside it", async () => {
    const patch = deferred();
    const withAddition = {
      ...OPEN,
      additions: [
        {
          id: "a1",
          added_at: "2026-09-22T08:00:00Z",
          undone: false,
          conversation_id: "c2",
          conversation_title: "Leak",
          proposal_id: "p2",
        },
      ],
    };
    const { calls } = api({
      "GET /api/thoughts/t1": json(200, withAddition),
      "PATCH /api/thoughts/t1": () => patch.promise,
    });
    const dialog = await openSheet();
    const box = within(dialog).getByRole("checkbox", { name: "Done" });
    const actions = ["Edit", "Delete", "Undo last addition"].map((name) =>
      within(dialog).getByRole("button", { name }),
    );

    fireEvent.click(box);

    await waitFor(() => expect(box).toBeDisabled());
    for (const action of actions) {
      expect(action).toBeDisabled();
      fireEvent.click(action);
    }
    expect(within(dialog).queryByRole("region", { name: "Edit thought" })).not.toBeInTheDocument();
    // No delete or undo dialog beside the sheet.
    expect(screen.getAllByRole("dialog")).toEqual([dialog]);

    patch.resolve(json(200, { ...DONE, additions: withAddition.additions }));

    await waitFor(() => expect(box).toBeEnabled());
    for (const action of actions) expect(action).toBeEnabled();
    expect(calls.filter((call) => call.method !== "GET")).toEqual([
      { method: "PATCH", path: "/api/thoughts/t1", body: { status: "done" } },
    ]);
  });

  it("turned off, sends status open and shows no done date", async () => {
    const { calls } = api({
      "GET /api/thoughts/t1": json(200, DONE),
      "PATCH /api/thoughts/t1": json(200, { ...OPEN, status_changed_at: "2026-09-24T09:00:00Z" }),
    });
    const dialog = await openSheet();
    const box = within(dialog).getByRole("checkbox", { name: "Done" });

    fireEvent.click(box);

    await waitFor(() => expect(box).not.toBeChecked());
    await waitFor(() => expect(box).toBeEnabled());
    expect(within(dialog).queryByText(/^Done on /)).not.toBeInTheDocument();
    expect(calls.filter((call) => call.method === "PATCH").map((call) => call.body)).toEqual([
      { status: "open" },
    ]);
  });

  it("unchecks again and shows the server's message when the PATCH fails", async () => {
    api({
      "GET /api/thoughts/t1": json(200, OPEN),
      "PATCH /api/thoughts/t1": errorResponse(422, "validation_error", "status: must be open or done"),
    });
    const dialog = await openSheet();
    const box = within(dialog).getByRole("checkbox", { name: "Done" });

    fireEvent.click(box);

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("status: must be open or done");
    expect(box).not.toBeChecked();
    expect(box).toBeEnabled();
    expect(within(dialog).queryByText(/^Done on /)).not.toBeInTheDocument();
  });

  it("is not shown in edit mode", async () => {
    api({ "GET /api/thoughts/t1": json(200, DONE) });
    const dialog = await openSheet();

    fireEvent.click(within(dialog).getByRole("button", { name: "Edit" }));

    await within(dialog).findByRole("region", { name: "Edit thought" });
    expect(within(dialog).queryByRole("checkbox", { name: "Done" })).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/^Done on /)).not.toBeInTheDocument();
  });
});
