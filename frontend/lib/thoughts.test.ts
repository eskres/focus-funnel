// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorResponse, fakeApi, json } from "@/test/fake-api";

import { ValidationError } from "./api";
import {
  deleteThought,
  listThoughts,
  STATUS_LABELS,
  THOUGHT_CHANGED_EVENT,
  THOUGHT_STATUSES,
  type ThoughtChanged,
  undoAddition,
  updateThought,
} from "./thoughts";
import { browserTimeZone } from "./time-zone";

const THOUGHT = {
  id: "t1",
  title: "Dentist in May",
  summary: "Book it.",
  tags: ["health"],
  category: null,
  raw_text: null,
  created_at: "2026-09-20T08:00:00Z",
  updated_at: "2026-09-22T08:00:00Z",
  origin: null,
};

function listen() {
  const seen: ThoughtChanged[] = [];
  const onChange = (event: Event) => seen.push((event as CustomEvent<ThoughtChanged>).detail);
  window.addEventListener(THOUGHT_CHANGED_EVENT, onChange);
  return { seen, stop: () => window.removeEventListener(THOUGHT_CHANGED_EVENT, onChange) };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("updateThought", () => {
  it("sends only the given fields as PATCH and announces the new title", async () => {
    const { calls } = fakeApi({ "PATCH /api/thoughts/t1": json(200, THOUGHT) });
    const { seen, stop } = listen();

    const thought = await updateThought("t1", { title: "Dentist in May", category: null });
    stop();

    expect(thought).toEqual(THOUGHT);
    expect(calls).toEqual([
      { method: "PATCH", path: "/api/thoughts/t1", body: { title: "Dentist in May", category: null } },
    ]);
    expect(seen).toEqual([{ id: "t1", title: "Dentist in May" }]);
  });

  it("announces the title from the answer when the change sends no title", async () => {
    const answer = { ...THOUGHT, title: "Dentist in June", tags: ["health", "teeth"] };
    fakeApi({ "PATCH /api/thoughts/t1": json(200, answer) });
    const { seen, stop } = listen();

    await updateThought("t1", { tags: ["health", "teeth"] });
    stop();

    expect(seen).toEqual([{ id: "t1", title: "Dentist in June" }]);
  });

  it("sends a status change alone as PATCH {status} and announces it", async () => {
    const answer = { ...THOUGHT, status: "done", status_changed_at: "2026-09-23T09:00:00Z" };
    const { calls } = fakeApi({ "PATCH /api/thoughts/t1": json(200, answer) });
    const { seen, stop } = listen();

    const thought = await updateThought("t1", { status: "done" });
    stop();

    expect(thought).toEqual(answer);
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({ method: "PATCH", path: "/api/thoughts/t1", body: { status: "done" } });
    // The body is exactly {"status":"done"}, with no other field.
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(init.body).toBe('{"status":"done"}');
    expect(seen).toEqual([{ id: "t1", title: "Dentist in May" }]);
  });

  it("throws the server's message and announces nothing when the change is refused", async () => {
    fakeApi({ "PATCH /api/thoughts/t1": errorResponse(422, "validation_error", "title: must not be empty") });
    const { seen, stop } = listen();

    const failure = updateThought("t1", { title: "" });

    await expect(failure).rejects.toBeInstanceOf(ValidationError);
    await expect(failure).rejects.toThrow("title: must not be empty");
    stop();
    expect(seen).toEqual([]);
  });
});

describe("deleteThought", () => {
  it("sends DELETE and announces the delete", async () => {
    const { calls } = fakeApi({ "DELETE /api/thoughts/t1": new Response(null, { status: 204 }) });
    const { seen, stop } = listen();

    await expect(deleteThought("t1")).resolves.toBeUndefined();
    stop();

    expect(calls).toEqual([{ method: "DELETE", path: "/api/thoughts/t1", body: undefined }]);
    expect(seen).toEqual([{ id: "t1", deleted: true }]);
  });

  it("announces nothing when the delete fails", async () => {
    fakeApi({ "DELETE /api/thoughts/t1": errorResponse(404, "not_found", "No such thought.") });
    const { seen, stop } = listen();

    await expect(deleteThought("t1")).rejects.toThrow("No such thought.");
    stop();
    expect(seen).toEqual([]);
  });
});

describe("listThoughts", () => {
  const ROW = {
    id: "t1",
    title: "Call the plumber",
    category: "task",
    tags: ["home"],
    status: "done",
    created_at: "2026-11-02T09:00:00Z",
    when: { start: "2026-11-04", end: null, time_zone: "Europe/Oslo" },
  };
  const LIST = "GET /api/thoughts";
  const sent = (calls: { path: string }[]) => new URL(calls[0].path, "http://localhost");

  it("sends each filter that is set, the zone, and the cursor encoded", async () => {
    const { calls } = fakeApi({ [LIST]: json(200, { items: [], next_cursor: null }) });

    await listThoughts(
      { category: "task", tag: "home", status: "open", filed_from: "2026-11-01", filed_to: "2026-11-30" },
      "c+/=",
    );

    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("GET");
    const url = sent(calls);
    expect(url.pathname).toBe("/api/thoughts");
    expect([...url.searchParams.entries()]).toEqual([
      ["category", "task"],
      ["tag", "home"],
      ["status", "open"],
      ["filed_from", "2026-11-01"],
      ["filed_to", "2026-11-30"],
      ["time_zone", browserTimeZone()],
      ["cursor", "c+/="],
    ]);
    // The cursor's +, / and = are escaped, so the server reads it back as sent.
    expect(calls[0].path).toContain("cursor=c%2B%2F%3D");
  });

  it("sends only the zone when no filter is set", async () => {
    const { calls } = fakeApi({ [LIST]: json(200, { items: [], next_cursor: null }) });

    await listThoughts({});

    expect([...sent(calls).searchParams.keys()]).toEqual(["time_zone"]);
    expect(sent(calls).searchParams.get("time_zone")).toBe(browserTimeZone());
  });

  it("sends the page size only when it is given", async () => {
    const { calls } = fakeApi({ [LIST]: json(200, { items: [], next_cursor: null }) });

    await listThoughts({ status: "done" }, "c1", 20);

    expect(sent(calls).searchParams.get("limit")).toBe("20");
    expect(sent(calls).searchParams.get("cursor")).toBe("c1");
  });

  it("keeps a free-text tag and category one value each", async () => {
    const fetchMock = vi.fn(async () => json(200, { items: [], next_cursor: null }));
    vi.stubGlobal("fetch", fetchMock);

    await listThoughts({ tag: "#home & status=done", category: "a+b/c" });

    const path = String((fetchMock.mock.calls[0] as unknown[])[0]);
    expect(path).not.toContain("#");
    const url = new URL(path, "http://localhost");
    expect(url.pathname).toBe("/api/thoughts");
    expect(url.searchParams.getAll("tag")).toEqual(["#home & status=done"]);
    expect(url.searchParams.getAll("category")).toEqual(["a+b/c"]);
    expect(url.searchParams.has("status")).toBe(false);
    expect(url.searchParams.has("cursor")).toBe(false);
  });

  it("parses the answer into rows and the next cursor", async () => {
    fakeApi({ [LIST]: json(200, { items: [ROW], next_cursor: "c2" }) });

    const list = await listThoughts({});

    expect(list).toEqual({ items: [ROW], next_cursor: "c2" });
    expect(list.items[0].status).toBe("done");
  });

  it("labels every status", () => {
    expect(THOUGHT_STATUSES).toEqual(["open", "done"]);
    expect(THOUGHT_STATUSES.map((status) => STATUS_LABELS[status])).toEqual(["Open", "Done"]);
  });
});

describe("undoAddition", () => {
  const ADDITION = {
    id: "a1",
    added_at: "2026-09-23T08:00:00Z",
    undone: false,
    conversation_id: "c1",
    conversation_title: "Teeth",
    proposal_id: "p1",
  };
  const UNDO = "POST /api/thoughts/t1/additions/a1/undo";

  it("announces the restored title once the undo answers", async () => {
    const restored = { ...THOUGHT, title: "Dentist", tags: [] };
    const { calls } = fakeApi({ [UNDO]: json(200, restored) });
    const { seen, stop } = listen();

    const thought = await undoAddition("t1", ADDITION);
    stop();

    expect(thought).toEqual(restored);
    expect(calls).toEqual([{ method: "POST", path: "/api/thoughts/t1/additions/a1/undo", body: undefined }]);
    expect(seen).toHaveLength(1);
    // The id and the restored title; `undone` names the card whose addition went.
    expect(seen[0]).toMatchObject({ id: "t1", title: "Dentist" });
  });

  it("announces nothing when the undo is refused", async () => {
    fakeApi({ [UNDO]: errorResponse(409, "thought_changed", "The thought changed since.") });
    const { seen, stop } = listen();

    await expect(undoAddition("t1", ADDITION)).rejects.toThrow("The thought changed since.");
    stop();
    expect(seen).toEqual([]);
  });
});
