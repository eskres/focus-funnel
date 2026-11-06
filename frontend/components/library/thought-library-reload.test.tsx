// @vitest-environment jsdom
// The Library page and the sheet (thought-library task 2.4): a row opens the
// thought, and the shown rows load again when the sheet closes or a change
// made in it is saved, with `listThoughts` mocked and the real sheet clients.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { redirectToLogin } from "@/lib/redirect-to-login";
import { closeThought } from "@/lib/thought-link";
import { THOUGHT_CHANGED_EVENT } from "@/lib/thoughts";
import { json } from "@/test/fake-api";
import {
  deferred,
  failure,
  fakeLibrary,
  holdList,
  listCalls,
  listed,
  page,
  row,
  rowButtons,
  rows,
  sheetApi,
  showMoreButton,
  thoughtList,
  thoughtOf,
  titles,
} from "@/test/library";

import { ThoughtLibrary } from "./thought-library";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => window.location.pathname,
}));
vi.mock("@/lib/thoughts", async (original) => ({
  ...(await original<typeof import("@/lib/thoughts")>()),
  listThoughts: vi.fn(),
}));

const LOADING = () => screen.queryByRole("status");
const NONE_YET = "No thoughts filed yet.";
const NO_MATCH = "No thoughts match these filters.";

beforeEach(() => {
  window.history.replaceState(null, "", "/app/library");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  listed().mockReset();
  window.history.replaceState(null, "", "/");
});

async function openPage() {
  const view = render(<ThoughtLibrary />);
  await waitFor(() => expect(LOADING()).not.toBeInTheDocument());
  return view;
}

async function settle() {
  await act(async () => undefined);
}

const filters = () => screen.getByRole("group", { name: "Filters" });

async function choose(label: string, value: string) {
  const before = listed().mock.calls.length;
  fireEvent.change(within(filters()).getByLabelText(label), { target: { value } });
  await waitFor(() => expect(listed().mock.calls.length).toBe(before + 1));
  await waitFor(() => expect(LOADING()).not.toBeInTheDocument());
}

async function setTag(value: string) {
  const before = listed().mock.calls.length;
  const input = within(filters()).getByLabelText("Tag");
  fireEvent.change(input, { target: { value } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(listed().mock.calls.length).toBe(before + 1));
  await waitFor(() => expect(LOADING()).not.toBeInTheDocument());
}

/** The calls a reload makes: each sends a page size. */
const reloadCalls = () => listCalls().filter((args) => args.length === 3);

async function openRow(title: string) {
  fireEvent.click(screen.getByRole("button", { name: title }));
  return screen.findByRole("dialog", { name: title });
}

function closeSheet() {
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }));
}

async function showMore(count: number) {
  fireEvent.click(showMoreButton()!);
  await waitFor(() => expect(rowButtons()).toHaveLength(count));
}

/** 120 rows shown, with "c3" as the cursor: three pages of 50, 50, and 20. */
async function show120() {
  listed()
    .mockResolvedValueOnce(page(rows(1, 50), "c1"))
    .mockResolvedValueOnce(page(rows(51, 50), "c2"))
    .mockResolvedValueOnce(page(rows(101, 20), "c3"));
  const view = await openPage();
  await showMore(100);
  await showMore(120);
  return view;
}

describe("a Library row opens the thought", () => {
  it("opens the sheet over the list, with the address naming the thought", async () => {
    const { server } = fakeLibrary(rows(1, 3));
    sheetApi(server);
    await openPage();

    const sheet = await openRow("Thought 2");

    expect(await within(sheet).findByText("About Thought 2.")).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe("/app/library?thought=t2");
    expect(titles()).toEqual(["Thought 1", "Thought 2", "Thought 3"]);
    expect(reloadCalls()).toEqual([]);
  });

  it("shows the sheet open for a copied address", async () => {
    window.history.replaceState(null, "", "/app/library?thought=t2");
    const { server } = fakeLibrary(rows(1, 3));
    sheetApi(server);

    render(<ThoughtLibrary />);

    const sheet = await screen.findByRole("dialog", { name: "Thought 2" });
    expect(await within(sheet).findByText("About Thought 2.")).toBeInTheDocument();
    await waitFor(() => expect(titles()).toEqual(["Thought 1", "Thought 2", "Thought 3"]));
  });

  it("closes the sheet on Back and keeps the rows", async () => {
    const { server } = fakeLibrary(rows(1, 3));
    sheetApi(server);
    await openPage();
    await openRow("Thought 2");

    window.history.back();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(window.location.pathname + window.location.search).toBe("/app/library");
    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    expect(titles()).toEqual(["Thought 1", "Thought 2", "Thought 3"]);
  });
});

describe("the Library reload", () => {
  it("starts once when the sheet closes, by Close and by Back, and not on open or a second row", async () => {
    const { server } = fakeLibrary(rows(1, 5));
    sheetApi(server);
    await openPage();
    expect(reloadCalls()).toEqual([]);

    await openRow("Thought 2");
    // A second row while the sheet is open: the id goes from one thought to another.
    await openRow("Thought 3");
    await settle();
    expect(window.location.search).toBe("?thought=t3");
    expect(reloadCalls()).toEqual([]);

    act(() => closeThought());
    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    expect(reloadCalls()).toEqual([[{}, undefined, 50]]);

    await openRow("Thought 1");
    await settle();
    expect(reloadCalls()).toHaveLength(1);

    window.history.back();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(reloadCalls()).toHaveLength(2));
    await settle();
    expect(reloadCalls()).toHaveLength(2);
    expect(titles()).toHaveLength(5);
  });

  it("drops an older reload's late answer once a newer reload has answered", async () => {
    const plumber = row(1, { title: "Call the plumber", category: "task" });
    const { server, serve } = fakeLibrary([plumber, row(2), row(3)]);
    const patch = deferred<void>();
    sheetApi(server, { held: { "PATCH /api/thoughts/t1": patch.promise } });
    await openPage();
    await choose("Status", "open");
    const sheet = await openRow("Call the plumber");
    fireEvent.click(within(sheet).getByRole("checkbox", { name: "Done" }));
    const closeReload = holdList(serve);

    closeSheet();
    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    // The PATCH answers: its event starts a newer reload, which answers without the row.
    patch.resolve();
    await waitFor(() => expect(titles()).toEqual(["Thought 2", "Thought 3"]));
    expect(reloadCalls()).toHaveLength(2);
    // The close reload answers late, with the old row.
    closeReload.release(page([plumber, row(2), row(3)]));
    await settle();

    expect(titles()).toEqual(["Thought 2", "Thought 3"]);
    expect(reloadCalls()).toEqual([
      [{ status: "open" }, undefined, 50],
      [{ status: "open" }, undefined, 50],
    ]);
  });

  it("stops listening at unmount", async () => {
    fakeLibrary(rows(1, 3));
    const view = await openPage();
    view.unmount();
    const before = listed().mock.calls.length;

    window.dispatchEvent(new CustomEvent(THOUGHT_CHANGED_EVENT, { detail: { id: "t1", title: "Thought 1" } }));
    await settle();

    expect(listed()).toHaveBeenCalledTimes(before);
  });

  it("sends no further request and sets no state when a reload answers after unmount", async () => {
    sheetApi({ db: rows(1, 120) });
    const view = await show120();
    await openRow("Thought 7");
    const reload = holdList();
    closeSheet();
    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    const error = vi.spyOn(console, "error");
    const before = listed().mock.calls.length;

    view.unmount();
    reload.release(page(rows(1, 100), "r1"));
    await settle();

    expect(listed()).toHaveBeenCalledTimes(before);
    expect(error).not.toHaveBeenCalled();
  });

  it.each(["Done", "Save"])("loads again once a %s answers after the sheet closed", async (action) => {
    const { server } = fakeLibrary(rows(1, 3));
    const patch = deferred<void>();
    sheetApi(server, { held: { "PATCH /api/thoughts/t1": patch.promise } });
    await openPage();
    await choose("Status", "open");
    const sheet = await openRow("Thought 1");
    if (action === "Done") {
      fireEvent.click(within(sheet).getByRole("checkbox", { name: "Done" }));
    } else {
      fireEvent.click(within(sheet).getByRole("button", { name: "Edit" }));
      const form = within(sheet).getByRole("region", { name: "Edit thought" });
      fireEvent.change(within(form).getByLabelText("Title"), { target: { value: "Call the plumber" } });
      fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    }

    closeSheet();
    // The close reload reads the thought before the change is saved.
    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    await settle();
    expect(titles()).toEqual(["Thought 1", "Thought 2", "Thought 3"]);

    patch.resolve();

    await waitFor(() => expect(reloadCalls()).toHaveLength(2));
    if (action === "Done") {
      await waitFor(() => expect(titles()).toEqual(["Thought 2", "Thought 3"]));
    } else {
      await waitFor(() => expect(titles()).toEqual(["Call the plumber", "Thought 2", "Thought 3"]));
    }
  });

  it("loads again once an undo answers after the sheet closed", async () => {
    const addition = {
      id: "a1",
      added_at: "2026-11-04T08:00:00Z",
      undone: false,
      conversation_id: "c1",
      conversation_title: "Chores",
      proposal_id: "p1",
    };
    const { server } = fakeLibrary([row(1, { tags: ["home"] }), row(2, { tags: ["home"] })]);
    const undo = deferred<void>();
    sheetApi(server, {
      held: { "POST /api/thoughts/t1/additions/a1/undo": undo.promise },
      routes: {
        "GET /api/thoughts/t1": () => json(200, thoughtOf(server.db[0], { additions: [addition] })),
        "POST /api/thoughts/t1/additions/a1/undo": () => {
          server.db[0] = { ...server.db[0], tags: [] };
          return json(200, thoughtOf(server.db[0], { additions: [{ ...addition, undone: true }] }));
        },
      },
    });
    await openPage();
    await setTag("home");
    const sheet = await openRow("Thought 1");
    fireEvent.click(await within(sheet).findByRole("button", { name: "Undo last addition" }));
    const ask = await screen.findByRole("dialog", { name: "Undo the last addition?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Undo" }));

    act(() => closeThought());
    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    await settle();
    expect(titles()).toEqual(["Thought 1", "Thought 2"]);

    undo.resolve();

    await waitFor(() => expect(reloadCalls()).toHaveLength(2));
    await waitFor(() => expect(titles()).toEqual(["Thought 2"]));
    expect(reloadCalls().at(-1)).toEqual([{ tag: "home" }, undefined, 50]);
  });

  it("drops a row deleted elsewhere once its sheet closes, with no alert", async () => {
    const { server } = fakeLibrary(rows(1, 3));
    sheetApi(server);
    await openPage();
    server.db.splice(1, 1);

    fireEvent.click(screen.getByRole("button", { name: "Thought 2" }));
    const sheet = await screen.findByRole("dialog");
    expect(await within(sheet).findByText("This thought no longer exists.")).toBeInTheDocument();
    closeSheet();

    await waitFor(() => expect(titles()).toEqual(["Thought 1", "Thought 3"]));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a title edited in the sheet at the same place", async () => {
    const { server } = fakeLibrary(rows(1, 5));
    sheetApi(server);
    await openPage();
    const sheet = await openRow("Thought 3");
    fireEvent.click(within(sheet).getByRole("button", { name: "Edit" }));
    const form = within(sheet).getByRole("region", { name: "Edit thought" });
    fireEvent.change(within(form).getByLabelText("Title"), { target: { value: "Renamed" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await screen.findByRole("dialog", { name: "Renamed" });

    closeSheet();

    await waitFor(() => expect(titles()).toEqual(["Thought 1", "Thought 2", "Renamed", "Thought 4", "Thought 5"]));
  });

  it("drops a thought deleted in the sheet", async () => {
    const { server } = fakeLibrary(rows(1, 3));
    sheetApi(server);
    await openPage();
    const sheet = await openRow("Thought 2");
    fireEvent.click(within(sheet).getByRole("button", { name: "Delete" }));
    const ask = await screen.findByRole("dialog", { name: "Delete this thought?" });

    fireEvent.click(within(ask).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(titles()).toEqual(["Thought 1", "Thought 3"]));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("drops a task marked done under the open filter", async () => {
    const { server } = fakeLibrary(rows(1, 3));
    sheetApi(server);
    await openPage();
    await choose("Status", "open");
    const sheet = await openRow("Thought 2");
    const done = within(sheet).getByRole("checkbox", { name: "Done" });
    fireEvent.click(done);
    await waitFor(() => expect(done).toBeEnabled());
    expect(done).toBeChecked();

    closeSheet();

    await waitFor(() => expect(titles()).toEqual(["Thought 1", "Thought 3"]));
    expect(reloadCalls().at(-1)).toEqual([{ status: "open" }, undefined, 50]);
  });

  it("keeps the place: 100 rows shown ask once for 100, and the row nodes stay", async () => {
    const { server, serve } = fakeLibrary(rows(1, 150));
    sheetApi(server);
    await openPage();
    await showMore(100);
    await openRow("Thought 80");
    const buttons = rowButtons();
    const items = within(thoughtList()).getAllByRole("listitem");
    const reload = holdList(serve);

    closeSheet();

    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    // While the reload runs: the same nodes, no loading status, no empty text.
    rowButtons().forEach((button, index) => expect(button).toBe(buttons[index]));
    within(thoughtList())
      .getAllByRole("listitem")
      .forEach((item, index) => expect(item).toBe(items[index]));
    expect(LOADING()).not.toBeInTheDocument();
    expect(screen.queryByText(NONE_YET)).not.toBeInTheDocument();
    expect(screen.queryByText(NO_MATCH)).not.toBeInTheDocument();

    reload.release();
    await waitFor(() => expect(showMoreButton()).toBeEnabled());

    expect(reloadCalls()).toEqual([[{}, undefined, 100]]);
    expect(rowButtons()).toHaveLength(100);
    rowButtons().forEach((button, index) => expect(button).toBe(buttons[index]));
  });

  it("loads no more rows than before: 50 shown ask once for 50 and still offer Show more", async () => {
    const { server } = fakeLibrary(rows(1, 200));
    sheetApi(server);
    await openPage();
    await openRow("Thought 4");

    closeSheet();

    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    await waitFor(() => expect(showMoreButton()).toBeEnabled());
    expect(reloadCalls()).toEqual([[{}, undefined, 50]]);
    expect(rowButtons()).toHaveLength(50);
  });

  it("loads 120 shown rows as 100 and then 20, and Show more goes on from the last answer", async () => {
    sheetApi({ db: rows(1, 200) });
    await show120();
    await openRow("Thought 110");
    listed()
      .mockResolvedValueOnce(page(rows(1, 100), "r1"))
      .mockResolvedValueOnce(page(rows(101, 20), "r2"))
      .mockResolvedValueOnce(page(rows(121, 50), "r3"));

    closeSheet();

    await waitFor(() => expect(reloadCalls()).toHaveLength(2));
    await waitFor(() => expect(showMoreButton()).toBeEnabled());
    expect(reloadCalls()).toEqual([
      [{}, undefined, 100],
      [{}, "r1", 20],
    ]);
    expect(rowButtons()).toHaveLength(120);

    await showMore(170);
    expect(listCalls().at(-1)).toEqual([{}, "r2"]);
  });

  it("drops a copied address's first page when the sheet closes before it arrives", async () => {
    window.history.replaceState(null, "", "/app/library?thought=t1");
    const { server } = fakeLibrary(rows(1, 80));
    sheetApi(server);
    const first = holdList();
    render(<ThoughtLibrary />);
    await screen.findByRole("dialog", { name: "Thought 1" });

    closeSheet();

    await waitFor(() => expect(rowButtons()).toHaveLength(50));
    first.release(page([row(99, { title: "Stale" })]));
    await settle();
    expect(rowButtons()).toHaveLength(50);
    expect(titles()).not.toContain("Stale");
    expect(reloadCalls()).toEqual([[{}, undefined, 50]]);
  });

  it("keeps the 120 rows and the cursor when a reload fails, and Try again runs the whole reload", async () => {
    sheetApi({ db: rows(1, 200) });
    await show120();
    await openRow("Thought 110");
    const buttons = rowButtons();
    listed()
      .mockResolvedValueOnce(page(rows(1, 100), "r1"))
      .mockRejectedValueOnce(failure("internal_error", "The list broke.", 500));

    closeSheet();

    expect(await screen.findByRole("alert")).toHaveTextContent("The list broke.");
    rowButtons().forEach((button, index) => expect(button).toBe(buttons[index]));
    expect(rowButtons()).toHaveLength(120);
    listed()
      .mockResolvedValueOnce(page(rows(1, 100), "r1"))
      .mockResolvedValueOnce(page(rows(101, 20), "r2"));

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(reloadCalls()).toHaveLength(4));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(reloadCalls().slice(2)).toEqual([
      [{}, undefined, 100],
      [{}, "r1", 20],
    ]);
    expect(rowButtons()).toHaveLength(120);
  });

  it("shows a 429 from a reload in the alert, keeps the old cursor, and does not redirect", async () => {
    sheetApi({ db: rows(1, 200) });
    await show120();
    await openRow("Thought 110");
    listed()
      .mockResolvedValueOnce(page(rows(1, 100), "r1"))
      .mockRejectedValueOnce(failure("rate_limited", "Too many requests. Try again in 30 seconds.", 429));

    closeSheet();

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests. Try again in 30 seconds.");
    expect(rowButtons()).toHaveLength(120);
    expect(redirectToLogin).not.toHaveBeenCalled();
    // The old cursor stays: Show more goes on from the 120th row.
    listed().mockResolvedValueOnce(page(rows(121, 10), null));
    await showMore(130);
    expect(listCalls().at(-1)).toEqual([{}, "c3"]);
  });

  it("sends the user to log in, with no alert, when a reload is unauthenticated", async () => {
    sheetApi({ db: rows(1, 200) });
    await show120();
    await openRow("Thought 110");
    listed()
      .mockResolvedValueOnce(page(rows(1, 100), "r1"))
      .mockRejectedValueOnce(failure("unauthenticated", "Log in again.", 401));

    closeSheet();

    await waitFor(() => expect(redirectToLogin).toHaveBeenCalledWith("/app/library"));
    await settle();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(rowButtons()).toHaveLength(120);
  });

  it("drops a reload's answers when a filter changes while it runs", async () => {
    const { server, serve } = fakeLibrary([row(1, { category: "task" }), row(2), row(3, { category: "task" })]);
    sheetApi(server);
    await openPage();
    await openRow("Thought 2");
    const reload = holdList(serve);
    closeSheet();
    await waitFor(() => expect(reloadCalls()).toHaveLength(1));

    await choose("Category", "task");
    await waitFor(() => expect(titles()).toEqual(["Thought 1", "Thought 3"]));
    reload.release();
    await settle();

    expect(titles()).toEqual(["Thought 1", "Thought 3"]);
  });

  it("turns Show more off while a reload runs", async () => {
    listed().mockResolvedValueOnce(page(rows(1, 50), "c1"));
    sheetApi({ db: rows(1, 50) });
    await openPage();
    await openRow("Thought 3");
    const reload = holdList();
    closeSheet();
    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    const before = listed().mock.calls.length;

    expect(showMoreButton()).toBeDisabled();
    fireEvent.click(showMoreButton()!);
    await settle();
    expect(listed()).toHaveBeenCalledTimes(before);

    reload.release(page(rows(1, 50), "c1"));
    await waitFor(() => expect(showMoreButton()).toBeEnabled());
  });

  it("drops a Show more answer that returns after a reload started", async () => {
    listed().mockResolvedValueOnce(page(rows(1, 50), "c1"));
    sheetApi({ db: rows(1, 100) });
    await openPage();
    const more = holdList();
    fireEvent.click(showMoreButton()!);
    await openRow("Thought 3");
    const reload = holdList();
    closeSheet();
    await waitFor(() => expect(reloadCalls()).toHaveLength(1));

    more.release(page(rows(51, 50), "c2"));
    await settle();
    reload.release(page(rows(1, 50), "c1"));
    await waitFor(() => expect(showMoreButton()).toBeEnabled());

    expect(rowButtons()).toHaveLength(50);
    expect(reloadCalls()).toEqual([[{}, undefined, 50]]);
  });

  it("asks for 50 under a filter with 10 rows, so a new thought shows as an 11th", async () => {
    const tasks = rows(1, 10, { category: "task" });
    const { server } = fakeLibrary([...tasks, ...rows(11, 5)]);
    sheetApi(server);
    await openPage();
    await choose("Category", "task");
    expect(rowButtons()).toHaveLength(10);
    expect(showMoreButton()).not.toBeInTheDocument();
    server.db.unshift(row(0, { title: "New task", category: "task" }));
    await openRow("Thought 4");

    closeSheet();

    await waitFor(() => expect(rowButtons()).toHaveLength(11));
    expect(titles()[0]).toBe("New task");
    expect(reloadCalls()).toEqual([[{ category: "task" }, undefined, 50]]);
  });

  it("says nothing matches when a reload under a filter answers no rows", async () => {
    const { server } = fakeLibrary([row(1)]);
    sheetApi(server);
    await openPage();
    await choose("Status", "open");
    await openRow("Thought 1");
    listed().mockResolvedValueOnce(page([]));

    closeSheet();

    expect(await screen.findByText(NO_MATCH)).toBeInTheDocument();
    expect(showMoreButton()).not.toBeInTheDocument();
  });

  it("says no thoughts are filed yet once the only thought is deleted in the sheet", async () => {
    const { server } = fakeLibrary([row(1)]);
    sheetApi(server);
    await openPage();
    const sheet = await openRow("Thought 1");
    fireEvent.click(within(sheet).getByRole("button", { name: "Delete" }));
    const ask = await screen.findByRole("dialog", { name: "Delete this thought?" });

    fireEvent.click(within(ask).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText(NONE_YET)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Thoughts" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
