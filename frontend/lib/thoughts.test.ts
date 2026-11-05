// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorResponse, fakeApi, json } from "@/test/fake-api";

import { ValidationError } from "./api";
import { deleteThought, THOUGHT_CHANGED_EVENT, type ThoughtChanged, updateThought } from "./thoughts";

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
