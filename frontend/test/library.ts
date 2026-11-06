// Helpers for the Library page tests (thought-library tasks 2.2 to 2.4): rows,
// a fake list server behind a mocked `listThoughts`, held requests, and a
// fetch stand-in for the sheet's own requests.
//
// The test file mocks `@/lib/thoughts` with `listThoughts: vi.fn()` and keeps
// the real update, delete, and undo clients.
import { screen, within } from "@testing-library/react";
import { vi } from "vitest";

import { createApiError } from "@/lib/api";
import { listThoughts, type ThoughtFilters, type ThoughtList, type ThoughtRow } from "@/lib/thoughts";

import { errorResponse, json } from "./fake-api";

export function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  let reject: (error: unknown) => void = () => undefined;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

const BASE = Date.UTC(2026, 10, 5, 12, 0);

/** Thought n of a list, newer for a smaller n. */
export const row = (n: number, extra: Partial<ThoughtRow> = {}): ThoughtRow => ({
  id: `t${n}`,
  title: `Thought ${n}`,
  category: null,
  tags: [],
  status: "open",
  created_at: new Date(BASE - n * 60_000).toISOString(),
  when: null,
  ...extra,
});

/** Thoughts `from` to `from + count - 1`, newest first. */
export const rows = (from: number, count: number, extra: Partial<ThoughtRow> = {}) =>
  Array.from({ length: count }, (_, index) => row(from + index, extra));

export const page = (items: ThoughtRow[], next: string | null = null): ThoughtList => ({
  items,
  next_cursor: next,
});

export const failure = (code: string, message: string, status: number) =>
  createApiError(code, message, status);

const cursorOf = (r: ThoughtRow) => `${r.created_at}|${r.id}`;
const keyOf = (r: ThoughtRow) => `${r.created_at}|${r.id}`;

export const listed = () => vi.mocked(listThoughts);

/** The arguments of each `listThoughts` call, as sent. */
export const listCalls = () => listed().mock.calls.map((args) => [...args]);

/**
 * A list server over `db`, newest filed first, which the test may change. It
 * filters by category, tag, and status, and pages with a cursor of the last row.
 */
export function fakeLibrary(initial: ThoughtRow[]) {
  const server = { db: [...initial] };
  const serve = (filters: ThoughtFilters, cursor?: string, limit = 50): ThoughtList => {
    let items = server.db.filter(
      (r) =>
        (!filters.category || r.category === filters.category) &&
        (!filters.tag || r.tags.includes(filters.tag)) &&
        (!filters.status || r.status === filters.status),
    );
    if (cursor) items = items.filter((r) => keyOf(r) < cursor);
    const shown = items.slice(0, limit);
    return page(shown, items.length > limit ? cursorOf(shown.at(-1)!) : null);
  };
  listed().mockImplementation(async (filters, cursor, limit) => serve(filters, cursor, limit));
  return { server, serve };
}

/**
 * Holds the next `listThoughts` call. `release()` answers it from the server
 * as it is then, or with the given list; `fail()` rejects it.
 */
export function holdList(serve?: (filters: ThoughtFilters, cursor?: string, limit?: number) => ThoughtList) {
  const gate = deferred<ThoughtList | undefined>();
  listed().mockImplementationOnce(async (filters, cursor, limit) => {
    const answer = await gate.promise;
    return answer ?? serve!(filters, cursor, limit);
  });
  return {
    release: (answer?: ThoughtList) => gate.resolve(answer),
    fail: (error: unknown) => gate.reject(error),
  };
}

/** A thought as `GET /api/thoughts/{id}` answers it, from its row. */
export const thoughtOf = (r: ThoughtRow, extra: Record<string, unknown> = {}) => ({
  id: r.id,
  title: r.title,
  summary: `About ${r.title}.`,
  tags: r.tags,
  category: r.category,
  raw_text: null,
  when: r.when,
  created_at: r.created_at,
  updated_at: r.created_at,
  origin: null,
  additions: [],
  status: r.status,
  status_changed_at: null,
  ...extra,
});

type Handler = (url: URL, init: RequestInit) => Response | Promise<Response>;

/**
 * The sheet's requests against the same server: GET, PATCH, and DELETE of one
 * thought change `server.db`. A request whose key ("METHOD /path") is in
 * `held` waits for that promise first; `routes` answer other requests.
 */
export function sheetApi(
  server: { db: ThoughtRow[] },
  options: { routes?: Record<string, Handler>; held?: Record<string, Promise<unknown>> } = {},
) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const key = `${method} ${url.pathname}`;
    const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    const hold = options.held?.[key];
    if (hold) await hold;
    const route = options.routes?.[key];
    if (route) return route(url, init);
    const match = /^\/api\/thoughts\/([^/]+)$/.exec(url.pathname);
    if (!match) throw new Error(`Unexpected request: ${key}`);
    const id = decodeURIComponent(match[1]);
    const index = server.db.findIndex((r) => r.id === id);
    if (index < 0) return errorResponse(404, "not_found", "No such thought.");
    if (method === "GET") return json(200, thoughtOf(server.db[index]));
    if (method === "PATCH") {
      server.db[index] = { ...server.db[index], ...(body as Partial<ThoughtRow>) };
      return json(200, thoughtOf(server.db[index]));
    }
    if (method === "DELETE") {
      server.db.splice(index, 1);
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected request: ${key}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls };
}

/** The Library's list. */
export const thoughtList = () => screen.getByRole("list", { name: "Thoughts" });

/** The row buttons, in order. */
export const rowButtons = () => within(thoughtList()).getAllByRole("button");

/** The shown titles, in order, read from each button's accessible name. */
export const titles = () =>
  screen.queryByRole("list", { name: "Thoughts" })
    ? rowButtons().map((button) => document.getElementById(button.getAttribute("aria-labelledby")!)!.textContent)
    : [];

export const showMoreButton = () => screen.queryByRole("button", { name: "Show more" });
