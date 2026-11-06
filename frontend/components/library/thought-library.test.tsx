// @vitest-environment jsdom
// The Library page (thought-library tasks 2.2 and 2.3): the list, its rows,
// "Show more", the page state, and the filters, with `listThoughts` mocked.

// Before any date is read: the browser's zone is west of UTC.
process.env.TZ = "America/Los_Angeles";

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CategoriesProvider } from "@/components/chat/categories-context";
import { redirectToLogin } from "@/lib/redirect-to-login";
import { FIXED_CATEGORIES } from "@/lib/thoughts";
import { fakeApi, json } from "@/test/fake-api";
import {
  failure,
  fakeLibrary,
  holdList,
  listCalls,
  listed,
  page,
  row,
  rowButtons,
  rows,
  showMoreButton,
  thoughtList,
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
  listed().mockReset();
  window.history.replaceState(null, "", "/");
});

/** Renders the page and waits for its first answer. */
async function openPage() {
  const view = render(<ThoughtLibrary />);
  await waitFor(() => expect(LOADING()).not.toBeInTheDocument());
  return view;
}

const filters = () => screen.getByRole("group", { name: "Filters" });
const field = (label: string) => within(filters()).getByLabelText(label);
const options = (label: string) =>
  within(field(label)).getAllByRole("option").map((option) => option.textContent);

function choose(label: string, value: string) {
  fireEvent.change(field(label), { target: { value } });
}

function setTag(value: string) {
  const input = field("Tag");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value } });
  fireEvent.keyDown(input, { key: "Enter" });
}

async function settle() {
  await act(async () => undefined);
}

const PLUMBER = row(2, {
  title: "Call the plumber",
  category: "task",
  tags: ["home"],
  status: "done",
  // 18:00 UTC is 10:00 on 2 November in California.
  created_at: "2026-11-02T18:00:00Z",
  when: { start: "2026-11-04", end: null, time_zone: "America/Los_Angeles" },
});
const PODCAST = row(1, {
  title: "Podcast about maps",
  category: "idea",
  // 03:00 UTC on 4 November is still 3 November in California.
  created_at: "2026-11-04T03:00:00Z",
});
const LOOSE = row(3, { title: "Loose note", created_at: "2026-11-01T17:00:00Z" });

describe("the Library list", () => {
  it("names the list and each row button by its title alone, described by the rest", async () => {
    fakeLibrary([PODCAST, PLUMBER, LOOSE]);

    await openPage();

    expect(thoughtList()).toBeInTheDocument();
    expect(titles()).toEqual(["Podcast about maps", "Call the plumber", "Loose note"]);
    for (const button of rowButtons()) {
      expect(button).not.toHaveAttribute("aria-label");
      expect(button).toHaveAttribute("aria-labelledby");
      expect(button).toHaveAttribute("aria-describedby");
    }
    const plumber = screen.getByRole("button", { name: "Call the plumber" });
    expect(plumber).toHaveAccessibleName("Call the plumber");
    for (const part of ["task", "home", "Filed", "Done"]) {
      expect(plumber).toHaveAccessibleDescription(expect.stringContaining(part));
    }
    expect(listCalls()).toEqual([[{}]]);
  });

  it("shows a row's title, category, tags, filed day, date, and Done", async () => {
    fakeLibrary([PLUMBER]);

    await openPage();

    const plumber = screen.getByRole("button", { name: "Call the plumber" });
    expect(within(plumber).getByText("Call the plumber")).toBeInTheDocument();
    expect(within(plumber).getByText("task")).toBeInTheDocument();
    expect(within(plumber).getByText("#home")).toBeInTheDocument();
    expect(within(plumber).getByText("Filed Mon 2 Nov 2026")).toBeInTheDocument();
    // The thought's own date, from lib/dates.ts.
    expect(within(plumber).getByText("Wed 4 Nov 2026")).toBeInTheDocument();
    expect(within(plumber).getByText("Done")).toBeInTheDocument();
    expect(plumber).toHaveAccessibleDescription("task #home Filed Mon 2 Nov 2026 Wed 4 Nov 2026 Done");
  });

  it("files a row under the browser's local day", async () => {
    fakeLibrary([PODCAST]);

    await openPage();

    expect(screen.getByRole("button", { name: "Podcast about maps" })).toHaveAccessibleDescription(
      "idea Filed Tue 3 Nov 2026",
    );
  });

  it("shows no status on an open thought", async () => {
    fakeLibrary([PODCAST]);

    await openPage();

    const podcast = screen.getByRole("button", { name: "Podcast about maps" });
    expect(within(podcast).queryByText("Done")).not.toBeInTheDocument();
    expect(within(podcast).queryByText("Open")).not.toBeInTheDocument();
  });

  it("shows an uncategorised row with no empty badge or tag list", async () => {
    fakeLibrary([LOOSE]);

    await openPage();

    const loose = screen.getByRole("button", { name: "Loose note" });
    expect(loose).toHaveAccessibleDescription("Filed Sun 1 Nov 2026");
    const meta = document.getElementById(loose.getAttribute("aria-describedby")!)!;
    // Only the filed day: no category badge, tag list, or status in their place.
    expect(meta.children).toHaveLength(1);
    expect(meta.children[0]).toHaveTextContent("Filed Sun 1 Nov 2026");
    expect(loose.querySelectorAll("[data-slot=badge]")).toHaveLength(0);
  });

  it("shows 50 rows, and Show more appends the next page with the answer's cursor", async () => {
    listed()
      .mockResolvedValueOnce(page(rows(1, 50), "c1"))
      .mockResolvedValueOnce(page(rows(51, 50), null));

    await openPage();
    expect(rowButtons()).toHaveLength(50);

    fireEvent.click(showMoreButton()!);

    await waitFor(() => expect(rowButtons()).toHaveLength(100));
    expect(listCalls()).toEqual([[{}], [{}, "c1"]]);
    expect(titles()[50]).toBe("Thought 51");
    expect(showMoreButton()).not.toBeInTheDocument();
  });

  it("says no thoughts are filed yet after an empty answer", async () => {
    listed().mockResolvedValue(page([]));

    await openPage();

    expect(screen.getByText(NONE_YET)).toBeInTheDocument();
    expect(screen.queryByText(NO_MATCH)).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Thoughts" })).not.toBeInTheDocument();
    expect(showMoreButton()).not.toBeInTheDocument();
  });

  it("shows the loading status, not an empty text, until the first answer", async () => {
    const first = holdList();
    render(<ThoughtLibrary />);

    expect(LOADING()).toHaveTextContent("Loading thoughts…");
    expect(screen.queryByText(NONE_YET)).not.toBeInTheDocument();
    expect(screen.queryByText(NO_MATCH)).not.toBeInTheDocument();

    first.release(page([]));
    expect(await screen.findByText(NONE_YET)).toBeInTheDocument();
    expect(LOADING()).not.toBeInTheDocument();

    // A filter's first page: the same, with the filter's empty text.
    const filtered = holdList();
    choose("Status", "done");
    expect(LOADING()).toBeInTheDocument();
    expect(screen.queryByText(NONE_YET)).not.toBeInTheDocument();
    expect(screen.queryByText(NO_MATCH)).not.toBeInTheDocument();

    filtered.release(page([]));
    expect(await screen.findByText(NO_MATCH)).toBeInTheDocument();
    expect(LOADING()).not.toBeInTheDocument();
  });

  it("turns Show more off while its request runs", async () => {
    listed().mockResolvedValueOnce(page(rows(1, 50), "c1"));
    await openPage();
    const more = holdList();

    fireEvent.click(showMoreButton()!);

    expect(showMoreButton()).toBeDisabled();
    fireEvent.click(showMoreButton()!);
    expect(listed()).toHaveBeenCalledTimes(2);
    more.release(page(rows(51, 10), "c2"));
    await waitFor(() => expect(showMoreButton()).toBeEnabled());
    expect(rowButtons()).toHaveLength(60);
  });

  it("shows a failed first load's message with Try again, which repeats it", async () => {
    listed()
      .mockRejectedValueOnce(failure("internal_error", "Something went wrong.", 500))
      .mockResolvedValueOnce(page(rows(1, 3)));

    render(<ThoughtLibrary />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
    expect(LOADING()).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(rowButtons()).toHaveLength(3));
    expect(listCalls()).toEqual([[{}], [{}]]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  for (const button of ["Try again", "Show more"]) {
    it(`keeps the rows when Show more fails, and ${button} sends the same request`, async () => {
      listed()
        .mockResolvedValueOnce(page(rows(1, 50), "c0"))
        .mockResolvedValueOnce(page(rows(1, 50), "c1"))
        .mockRejectedValueOnce(failure("internal_error", "The list broke.", 500));
      await openPage();
      choose("Status", "open");
      // The status filter's first page.
      await waitFor(() => expect(listed()).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(showMoreButton()).toBeEnabled());

      fireEvent.click(showMoreButton()!);

      expect(await screen.findByRole("alert")).toHaveTextContent("The list broke.");
      expect(rowButtons()).toHaveLength(50);
      expect(showMoreButton()).toBeEnabled();

      listed().mockResolvedValueOnce(page(rows(51, 50), null));
      fireEvent.click(screen.getByRole("button", { name: button }));

      await waitFor(() => expect(rowButtons()).toHaveLength(100));
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(listCalls().slice(-2)).toEqual([
        [{ status: "open" }, "c1"],
        [{ status: "open" }, "c1"],
      ]);
    });
  }

  it("sends the user to log in when the first load is unauthenticated", async () => {
    listed().mockRejectedValueOnce(failure("unauthenticated", "Log in again.", 401));

    render(<ThoughtLibrary />);

    await waitFor(() => expect(redirectToLogin).toHaveBeenCalledWith("/app/library"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("sends the user to log in, with no alert, when Show more is unauthenticated", async () => {
    listed()
      .mockResolvedValueOnce(page(rows(1, 50), "c1"))
      .mockRejectedValueOnce(failure("unauthenticated", "Log in again.", 401));
    await openPage();

    fireEvent.click(showMoreButton()!);

    await waitFor(() => expect(redirectToLogin).toHaveBeenCalledWith("/app/library"));
    await settle();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(rowButtons()).toHaveLength(50);
  });
});

describe("the Library filters", () => {
  const TASKS = [
    row(1, { category: "task", tags: ["home"], created_at: "2026-11-03T18:00:00Z" }),
    row(2, { category: "idea", created_at: "2026-11-02T18:00:00Z" }),
  ];

  it.each([
    ["Category", "task", { category: "task" }],
    ["Status", "done", { status: "done" }],
  ])("asks for the first page when the %s select changes", async (label, value, expected) => {
    fakeLibrary(TASKS);
    await openPage();

    choose(label, value);

    await waitFor(() => expect(listed()).toHaveBeenCalledTimes(2));
    expect(listCalls().at(-1)).toEqual([expected]);
  });

  it("asks for the first page when the Tag field is applied, on Enter or on blur", async () => {
    fakeLibrary(TASKS);
    await openPage();

    setTag("home");
    await waitFor(() => expect(listed()).toHaveBeenCalledTimes(2));
    expect(listCalls().at(-1)).toEqual([{ tag: "home" }]);

    const input = field("Tag");
    fireEvent.change(input, { target: { value: " garden " } });
    fireEvent.blur(input);
    await waitFor(() => expect(listed()).toHaveBeenCalledTimes(3));
    expect(listCalls().at(-1)).toEqual([{ tag: "garden" }]);

    // A blank tag is no tag.
    setTag("   ");
    await waitFor(() => expect(listed()).toHaveBeenCalledTimes(4));
    expect(listCalls().at(-1)).toEqual([{}]);
  });

  it.each([
    ["Filed from", { filed_from: "2026-11-01" }],
    ["Filed to", { filed_to: "2026-11-01" }],
  ])("asks for the first page when %s is set", async (label, expected) => {
    fakeLibrary(TASKS);
    await openPage();

    expect(field(label)).toHaveAttribute("min", "1900-01-01");
    expect(field(label)).toHaveAttribute("max", "9998-12-31");
    choose(label, "2026-11-01");

    await waitFor(() => expect(listed()).toHaveBeenCalledTimes(2));
    expect(listCalls().at(-1)).toEqual([expected]);
  });

  it("sends every filter together, with no cursor", async () => {
    fakeLibrary(TASKS);
    await openPage();

    choose("Category", "task");
    setTag("home");
    choose("Status", "open");
    choose("Filed from", "2026-11-01");
    choose("Filed to", "2026-11-30");

    await waitFor(() => expect(listed()).toHaveBeenCalledTimes(6));
    expect(listCalls().at(-1)).toEqual([
      { category: "task", tag: "home", status: "open", filed_from: "2026-11-01", filed_to: "2026-11-30" },
    ]);
    await waitFor(() => expect(titles()).toEqual(["Thought 1"]));
  });

  it("clears the rows and asks for the first page when a filter changes after Show more", async () => {
    listed()
      .mockResolvedValueOnce(page(rows(1, 50), "c1"))
      .mockResolvedValueOnce(page(rows(51, 50), "c2"));
    await openPage();
    fireEvent.click(showMoreButton()!);
    await waitFor(() => expect(rowButtons()).toHaveLength(100));
    const first = holdList();

    choose("Category", "task");

    expect(screen.queryByRole("list", { name: "Thoughts" })).not.toBeInTheDocument();
    expect(LOADING()).toBeInTheDocument();
    expect(screen.queryByText(NO_MATCH)).not.toBeInTheDocument();
    expect(screen.queryByText(NONE_YET)).not.toBeInTheDocument();
    expect(listCalls().at(-1)).toEqual([{ category: "task" }]);

    first.release(page(rows(1, 50, { category: "task" }), "c3"));
    await waitFor(() => expect(rowButtons()).toHaveLength(50));
    expect(showMoreButton()).toBeEnabled();
  });

  it("drops an answer for an older filter that arrives after the change", async () => {
    listed().mockResolvedValueOnce(page(rows(1, 5)));
    await openPage();
    const older = holdList();
    choose("Category", "task");
    const newer = holdList();
    choose("Category", "idea");

    newer.release(page([row(9, { title: "An idea", category: "idea" })]));
    await waitFor(() => expect(titles()).toEqual(["An idea"]));
    older.release(page([row(8, { title: "A task", category: "task" })]));
    await settle();

    expect(titles()).toEqual(["An idea"]);
    expect(field("Category")).toHaveValue("idea");
  });

  it("keeps the filters when Show more asks for the next page", async () => {
    listed()
      .mockResolvedValueOnce(page(rows(1, 5)))
      .mockResolvedValueOnce(page(rows(1, 50), "c-home"))
      .mockResolvedValueOnce(page(rows(1, 50), "c-open"))
      .mockResolvedValueOnce(page(rows(51, 50), null));
    await openPage();
    setTag("home");
    await waitFor(() => expect(listed()).toHaveBeenCalledTimes(2));
    choose("Status", "open");
    await waitFor(() => expect(showMoreButton()).toBeEnabled());

    fireEvent.click(showMoreButton()!);

    await waitFor(() => expect(rowButtons()).toHaveLength(100));
    expect(listCalls().at(-1)).toEqual([{ tag: "home", status: "open" }, "c-open"]);
  });

  it("asks nothing when the Tag field is left without a change", async () => {
    listed()
      .mockResolvedValueOnce(page(rows(1, 5)))
      .mockResolvedValueOnce(page(rows(1, 50), "c1"))
      .mockResolvedValueOnce(page(rows(51, 50), "c2"));
    await openPage();
    setTag("home");
    await waitFor(() => expect(showMoreButton()).toBeEnabled());
    fireEvent.click(showMoreButton()!);
    await waitFor(() => expect(rowButtons()).toHaveLength(100));
    const before = listed().mock.calls.length;

    const input = field("Tag");
    fireEvent.focus(input);
    fireEvent.blur(input);
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "Enter" });
    // The same text with spaces around it, trimmed, is the tag applied.
    fireEvent.change(input, { target: { value: " home " } });
    fireEvent.blur(input);
    await settle();

    expect(listed()).toHaveBeenCalledTimes(before);
    expect(rowButtons()).toHaveLength(100);
  });

  it("applies a filed day only once the year is whole", async () => {
    fakeLibrary(TASKS);
    await openPage();

    for (const value of ["0002-11-01", "0020-11-01", "0202-11-01", "2026-11-01"]) {
      choose("Filed from", value);
    }

    await waitFor(() => expect(listed()).toHaveBeenCalledTimes(2));
    await settle();
    expect(listCalls()).toEqual([[{}], [{ filed_from: "2026-11-01" }]]);
  });

  it("lists again with no filed_from when the field is emptied, and not when it was empty", async () => {
    fakeLibrary(TASKS);
    await openPage();
    choose("Filed from", "2026-11-01");
    await waitFor(() => expect(listed()).toHaveBeenCalledTimes(2));

    choose("Filed from", "");
    await waitFor(() => expect(listed()).toHaveBeenCalledTimes(3));
    expect(listCalls().at(-1)).toEqual([{}]);

    choose("Filed from", "");
    await settle();
    expect(listed()).toHaveBeenCalledTimes(3);
  });

  it("shows no alert for an older filter's 422 that arrives after a newer answer", async () => {
    listed().mockResolvedValueOnce(page(rows(1, 5)));
    await openPage();
    const older = holdList();
    choose("Filed from", "2026-11-01");
    const newer = holdList();
    choose("Filed from", "2026-11-02");

    newer.release(page([row(1)]));
    await waitFor(() => expect(titles()).toEqual(["Thought 1"]));
    older.fail(failure("validation_error", "query.filed_from: Input should be a valid date", 422));
    await settle();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(titles()).toEqual(["Thought 1"]);
  });

  it("clears a failed filter's alert once the next filter change succeeds", async () => {
    listed()
      .mockResolvedValueOnce(page(rows(1, 5)))
      .mockRejectedValueOnce(failure("validation_error", "status: must be open or done", 422))
      .mockResolvedValueOnce(page([row(1)]));
    await openPage();

    choose("Status", "done");
    expect(await screen.findByRole("alert")).toHaveTextContent("status: must be open or done");
    choose("Category", "task");

    await waitFor(() => expect(titles()).toEqual(["Thought 1"]));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers Any status and the label of every status, in order", async () => {
    fakeLibrary(TASKS);
    await openPage();

    expect(options("Status")).toEqual(["Any status", "Open", "Done"]);
  });

  it("offers Any category and the user's categories, inside the categories provider", async () => {
    fakeApi({ "GET /api/settings/categories": json(200, { fixed: FIXED_CATEGORIES, added: ["reading"] }) });
    fakeLibrary(TASKS);
    render(
      <CategoriesProvider>
        <ThoughtLibrary />
      </CategoriesProvider>,
    );

    await waitFor(() => expect(options("Category")).toContain("reading"));
    expect(options("Category")).toEqual(["Any category", ...FIXED_CATEGORIES, "reading"]);

    choose("Category", "reading");
    await waitFor(() => expect(listCalls().at(-1)).toEqual([{ category: "reading" }]));
  });

  it("says no thoughts match when nothing passes the filters", async () => {
    fakeLibrary(TASKS);
    await openPage();

    setTag("nowhere");

    expect(await screen.findByText(NO_MATCH)).toBeInTheDocument();
    expect(screen.queryByText(NONE_YET)).not.toBeInTheDocument();
  });
});
