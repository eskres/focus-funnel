// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { closeThought, openThought } from "@/lib/thought-link";
import { detail, errorResponse, fakeApi, json, loadout } from "@/test/fake-api";

import { CategoriesProvider } from "./categories-context";
import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => window.location.pathname,
}));

const ORIGIN = {
  conversation_id: "c1",
  conversation_title: "Milk",
  archived: false,
  proposal_id: "p1",
  proposed_at: "2026-09-20T07:59:00Z",
};

const THOUGHT = {
  id: "t1",
  title: "Oat milk",
  summary: "Buy oat milk on the way home.",
  tags: ["groceries", "errands"],
  category: "task",
  raw_text: "buy oat milk, the barista one",
  created_at: "2026-09-20T08:00:00Z",
  updated_at: "2026-09-21T08:00:00Z",
  origin: ORIGIN,
};

const CATEGORIES = { fixed: ["task", "idea", "decision", "note", "reference"], added: ["recipe"] };
const PATCH = "PATCH /api/thoughts/t1";
const DELETE = "DELETE /api/thoughts/t1";

function api(routes: Parameters<typeof fakeApi>[0]) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/settings/categories": json(200, CATEGORIES),
    "GET /api/conversations/c1": json(200, detail()),
    "GET /api/thoughts/t1": json(200, THOUGHT),
    ...routes,
  });
}

function at(address: string) {
  window.history.replaceState(null, "", address);
}

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** The chat with the thought sheet open on t1, once the thought has loaded. */
async function openSheet(thought: { title: string } = THOUGHT) {
  // Opened as a link opens it, so Back closes it.
  at("/app/c1");
  openThought("t1");
  render(
    <CategoriesProvider>
      <Chat conversationId="c1" />
    </CategoriesProvider>,
  );
  const sheet = await screen.findByRole("dialog", { name: thought.title });
  await within(sheet).findByRole("button", { name: "Edit" });
  return sheet;
}

function startEdit(sheet: HTMLElement) {
  fireEvent.click(within(sheet).getByRole("button", { name: "Edit" }));
  return within(sheet).getByRole("region", { name: "Edit thought" });
}

function type(form: HTMLElement, label: string | RegExp, value: string) {
  fireEvent.change(within(form).getByLabelText(label), { target: { value } });
}

type Call = { method: string; path: string; body: unknown };
const changes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  at("/");
});

describe("editing a thought in the sheet", () => {
  it("fills the four fields, and keeps the raw text and origin read-only", async () => {
    api({});
    const sheet = await openSheet();

    const form = startEdit(sheet);

    expect(within(form).getByLabelText("Title")).toHaveValue("Oat milk");
    expect(within(form).getByLabelText("Summary")).toHaveValue("Buy oat milk on the way home.");
    expect(within(form).getByLabelText(/Tags/)).toHaveValue("groceries, errands");
    expect(within(form).getByLabelText("Category")).toHaveValue("task");
    // Three text fields and the category: none of them holds the raw text.
    expect(within(sheet).getAllByRole("textbox")).toHaveLength(3);
    for (const field of within(sheet).getAllByRole("textbox")) {
      expect(field).not.toHaveValue("buy oat milk, the barista one");
    }
    const raw = within(sheet).getByRole("region", { name: "Raw text" });
    expect(raw).toHaveTextContent("buy oat milk, the barista one");
    expect(within(raw).queryByRole("textbox")).not.toBeInTheDocument();
    const origin = within(sheet).getByRole("region", { name: "Origin" });
    expect(within(origin).getByRole("link", { name: "Milk" })).toBeInTheDocument();
    expect(within(origin).queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("saves only the changed fields and shows the answer with the new changed date", async () => {
    const answer = {
      ...THOUGHT,
      title: "Dentist in May",
      tags: ["health", "teeth"],
      updated_at: "2026-10-02T09:30:00Z",
    };
    const { calls } = api({ [PATCH]: json(200, answer) });
    const sheet = await openSheet();
    const form = startEdit(sheet);

    type(form, "Title", "  Dentist in May ");
    type(form, /Tags/, "Health, #teeth");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    const saved = await screen.findByRole("dialog", { name: "Dentist in May" });
    expect(changes(calls)).toEqual([
      { method: "PATCH", path: "/api/thoughts/t1", body: { title: "Dentist in May", tags: ["Health", "#teeth"] } },
    ]);
    expect(within(saved).queryByRole("region", { name: "Edit thought" })).not.toBeInTheDocument();
    // The server's cleaned tags, and the later "changed" date, come from its answer.
    expect(within(saved).getByText("#health")).toBeInTheDocument();
    expect(within(saved).getByText("#teeth")).toBeInTheDocument();
    expect(
      within(saved).getByText(`Filed ${when(THOUGHT.created_at)} · changed ${when(answer.updated_at)}`),
    ).toBeInTheDocument();
    // The origin is the same after the edit.
    expect(within(within(saved).getByRole("region", { name: "Origin" })).getByRole("link", { name: "Milk" }))
      .toBeInTheDocument();
  });

  it("sends each field alone, and None as no category", async () => {
    const { calls } = api({ [PATCH]: (_url, init) => json(200, { ...THOUGHT, ...JSON.parse(String(init.body)) }) });
    const sheet = await openSheet();

    let form = startEdit(sheet);
    type(form, "Summary", "Buy two cartons.");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await within(sheet).findByText("Buy two cartons.");

    form = startEdit(sheet);
    type(form, "Category", "");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(within(sheet).queryByText("task")).not.toBeInTheDocument());

    expect(changes(calls).map((c) => c.body)).toEqual([
      { summary: "Buy two cartons." },
      { category: null },
    ]);
  });

  it("sends nothing and leaves edit mode when no field changed", async () => {
    const { calls } = api({});
    const sheet = await openSheet();
    const form = startEdit(sheet);

    // Only spaces around the text and between tags: the same values.
    type(form, "Title", " Oat milk ");
    type(form, /Tags/, "groceries,errands , ");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(within(sheet).queryByRole("region", { name: "Edit thought" })).not.toBeInTheDocument(),
    );
    expect(within(sheet).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(changes(calls)).toEqual([]);
  });

  it("keeps edit mode and the text, and shows the message naming the field, when the save is refused", async () => {
    const long = "x".repeat(201);
    api({
      [PATCH]: errorResponse(422, "validation_error", "title: must be at most 200 characters"),
    });
    const sheet = await openSheet();
    const form = startEdit(sheet);

    type(form, "Title", long);
    type(form, "Summary", "Changed too.");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent("title: must be at most 200 characters");
    expect(within(form).getByLabelText("Title")).toHaveValue(long);
    expect(within(form).getByLabelText("Summary")).toHaveValue("Changed too.");
    expect(within(form).getByRole("button", { name: "Save" })).toBeEnabled();
    // The sheet still names the thought as it is stored.
    expect(screen.getByRole("dialog", { name: "Oat milk" })).toBe(sheet);
  });

  it.each([
    ["title", "Title", "Title must not be empty."],
    ["summary", "Summary", "Summary must not be empty."],
  ])("turns Save off, naming the field, while the %s is empty", async (_field, label, note) => {
    const { calls } = api({});
    const sheet = await openSheet();
    const form = startEdit(sheet);

    type(form, label, "   ");

    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
    expect(within(form).getByText(note)).toBeInTheDocument();
    expect(within(form).getByLabelText(label)).toHaveValue("   ");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    expect(changes(calls)).toEqual([]);
  });

  it("keeps a removed category the thought has as a choice, and does not send it on a title edit", async () => {
    const { calls } = api({
      "GET /api/thoughts/t1": json(200, { ...THOUGHT, category: "trip" }),
      [PATCH]: json(200, { ...THOUGHT, category: "trip", title: "Lisbon trip" }),
    });
    const sheet = await openSheet();
    const form = startEdit(sheet);
    const category = within(form).getByLabelText("Category");

    await waitFor(() =>
      expect(within(category).getAllByRole("option").map((o) => o.textContent)).toEqual([
        "None",
        "task",
        "idea",
        "decision",
        "note",
        "reference",
        "recipe",
        "trip",
      ]),
    );
    expect(category).toHaveValue("trip");
    // Picking another category keeps the removed one a choice.
    type(form, "Category", "idea");
    expect(within(category).getByRole("option", { name: "trip" })).toBeInTheDocument();
    type(form, "Category", "trip");

    type(form, "Title", "Lisbon trip");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await screen.findByRole("dialog", { name: "Lisbon trip" });
    expect(changes(calls).map((c) => c.body)).toEqual([{ title: "Lisbon trip" }]);
  });

  it("drops the edit on Cancel and shows the thought as it was", async () => {
    const { calls } = api({});
    const sheet = await openSheet();
    let form = startEdit(sheet);

    type(form, "Summary", "Something else.");
    fireEvent.click(within(form).getByRole("button", { name: "Cancel" }));

    expect(within(sheet).queryByRole("region", { name: "Edit thought" })).not.toBeInTheDocument();
    expect(within(sheet).getByText("Buy oat milk on the way home.")).toBeInTheDocument();
    form = startEdit(sheet);
    expect(within(form).getByLabelText("Summary")).toHaveValue("Buy oat milk on the way home.");
    expect(changes(calls)).toEqual([]);
  });

  it.each([
    ["the Close button", (sheet: HTMLElement) => fireEvent.click(within(sheet).getByRole("button", { name: "Close" }))],
    ["Back", () => window.history.back()],
    ["closeThought", () => closeThought()],
  ])("drops the edit when the sheet is closed with %s", async (_how, close) => {
    const { calls } = api({});
    const sheet = await openSheet();
    const form = startEdit(sheet);
    type(form, "Title", "Half-typed");

    close(sheet);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    openThought("t1");

    const again = await screen.findByRole("dialog", { name: "Oat milk" });
    expect(within(again).queryByRole("region", { name: "Edit thought" })).not.toBeInTheDocument();
    expect(within(again).queryByDisplayValue("Half-typed")).not.toBeInTheDocument();
    expect(changes(calls)).toEqual([]);
  });
});

describe("deleting a thought in the sheet", () => {
  async function askToDelete(sheet: HTMLElement) {
    fireEvent.click(within(sheet).getByRole("button", { name: "Delete" }));
    return screen.findByRole("dialog", { name: "Delete this thought?" });
  }

  it("asks in a dialog that names the thought, and Cancel keeps it", async () => {
    const { calls } = api({});
    const sheet = await openSheet();

    const ask = await askToDelete(sheet);

    expect(ask).toHaveTextContent("“Oat milk” is deleted for good. This cannot be undone.");
    fireEvent.click(within(ask).getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Delete this thought?" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("dialog", { name: "Oat milk" })).toHaveTextContent("Buy oat milk on the way home.");
    expect(window.location.search).toBe("?thought=t1");
    expect(changes(calls)).toEqual([]);
  });

  it("closes only the dialog on Escape or a press inside it, and the sheet stays", async () => {
    const { calls } = api({});
    const sheet = await openSheet();

    let ask = await askToDelete(sheet);
    const cancel = within(ask).getByRole("button", { name: "Cancel" });
    fireEvent.pointerDown(cancel);
    fireEvent.mouseDown(cancel);
    fireEvent.pointerUp(cancel);
    fireEvent.mouseUp(cancel);
    fireEvent.click(cancel);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Delete this thought?" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("dialog", { name: "Oat milk" })).toBeInTheDocument();

    ask = await askToDelete(sheet);
    fireEvent.keyDown(ask, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Delete this thought?" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("dialog", { name: "Oat milk" })).toBeInTheDocument();
    expect(window.location.search).toBe("?thought=t1");
    expect(changes(calls)).toEqual([]);
  });

  it("deletes on confirm, closes the sheet, and keeps the composer's text", async () => {
    const { calls } = api({ [DELETE]: new Response(null, { status: 204 }) });
    const sheet = await openSheet();
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "half-written" } });

    const ask = await askToDelete(sheet);
    fireEvent.click(within(ask).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(changes(calls)).toEqual([{ method: "DELETE", path: "/api/thoughts/t1", body: undefined }]);
    expect(window.location.pathname + window.location.search).toBe("/app/c1");
    expect(screen.getByLabelText("Message")).toHaveValue("half-written");
  });

  it("shows why a delete failed in the dialog and keeps the sheet open", async () => {
    api({ [DELETE]: errorResponse(502, "backend_unreachable", "The server could not be reached.") });
    const sheet = await openSheet();

    const ask = await askToDelete(sheet);
    fireEvent.click(within(ask).getByRole("button", { name: "Delete" }));

    expect(await within(ask).findByRole("alert")).toHaveTextContent("The server could not be reached.");
    expect(screen.getByRole("dialog", { name: "Delete this thought?" })).toBe(ask);
    fireEvent.click(within(ask).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Delete this thought?" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("dialog", { name: "Oat milk" })).toHaveTextContent("Buy oat milk on the way home.");
    expect(window.location.search).toBe("?thought=t1");
  });
});
