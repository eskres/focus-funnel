"use client";

// The Library page: the user's thoughts, newest filed first, 50 at a time,
// with filters (thought-library design decisions 1, 6, 7, 9, and 10). A row
// opens the thought in the side sheet over the list; the shown rows load
// again when the sheet closes or a thought changes, so the user keeps their
// place and sees the change.
import { Fragment, type KeyboardEvent, type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";

import { useCategories } from "@/components/chat/categories-context";
import { ThoughtSheet } from "@/components/chat/thought-sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { UnauthenticatedError } from "@/lib/api";
import { formatDay, formatWhen, localToday } from "@/lib/dates";
import { redirectToLogin } from "@/lib/redirect-to-login";
import { openThought, useOpenThought } from "@/lib/thought-link";
import {
  listThoughts,
  STATUS_LABELS,
  THOUGHT_CHANGED_EVENT,
  THOUGHT_STATUSES,
  type ThoughtFilters,
  type ThoughtRow,
  type ThoughtStatus,
} from "@/lib/thoughts";

/** One page, and the least a reload asks for. */
export const PAGE = 50;
/** The most one request may ask for. */
const MOST = 100;
/** The filed days the server takes (design decision 4). */
export const FIRST_DAY = "1900-01-01";
export const LAST_DAY = "9998-12-31";

type DateFilter = "filed_from" | "filed_to";

/** Whether a date field's value is a whole day the server takes. */
function inRange(day: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(day) && day >= FIRST_DAY && day <= LAST_DAY;
}

function hasFilter(filters: ThoughtFilters): boolean {
  return Object.values(filters).some(Boolean);
}

/** "Filed Mon 2 Nov 2026": the day `created_at` falls on in the browser's zone. */
export function filedDay(createdAt: string): string {
  return `Filed ${formatDay(localToday(new Date(createdAt)))}`;
}

/** What failed, and which request "Try again" repeats. */
type Failure = { message: string; retry: "first" | "more" | "reload" };

export function ThoughtLibrary() {
  const categories = useCategories();
  const openId = useOpenThought();
  const wasOpen = useRef(openId);

  const [filters, setFilters] = useState<ThoughtFilters>({});
  // Null until the current generation's first answer: the loading status.
  const [rows, setRows] = useState<ThoughtRow[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [tagText, setTagText] = useState("");
  const [dayText, setDayText] = useState<Record<DateFilter, string>>({ filed_from: "", filed_to: "" });

  // The latest filters, rows, and cursor, for requests that start from an
  // event or a retry, so they never read an old render's copy.
  const now = useRef<{ filters: ThoughtFilters; rows: ThoughtRow[] | null; cursor: string | null }>({
    filters: {},
    rows: null,
    cursor: null,
  });
  // Each filter change and reload takes a new number; an answer or a failure
  // for an older one is dropped. Unmounting takes one too, so nothing in
  // flight sets state or sends a further request.
  const generation = useRef(0);

  const show = useCallback((next: ThoughtRow[] | null, nextCursor: string | null) => {
    now.current = { ...now.current, rows: next, cursor: nextCursor };
    setRows(next);
    setCursor(nextCursor);
  }, []);

  /** Says what failed, or sends the user to log in; only for the current generation. */
  const fail = useCallback((mine: number, error: unknown, retry: Failure["retry"]) => {
    if (mine !== generation.current) return;
    if (error instanceof UnauthenticatedError) {
      redirectToLogin(window.location.pathname + window.location.search);
      return;
    }
    setBusy(false);
    setFailure({
      message: error instanceof Error ? error.message : "The thoughts could not be loaded.",
      retry,
    });
  }, []);

  /** Asks for the first page; its answer shows only while `mine` is current. */
  const fetchFirst = useCallback(
    (mine: number, next: ThoughtFilters) => {
      listThoughts(next).then(
        (list) => {
          if (mine !== generation.current) return;
          show(list.items, list.next_cursor);
          setBusy(false);
        },
        (error: unknown) => fail(mine, error, "first"),
      );
    },
    [fail, show],
  );

  /** The first page for these filters, with the rows cleared. */
  const loadFirst = useCallback(
    (next: ThoughtFilters) => {
      const mine = ++generation.current;
      now.current = { filters: next, rows: null, cursor: null };
      setFilters(next);
      show(null, null);
      setFailure(null);
      setBusy(true);
      fetchFirst(mine, next);
    },
    [fetchFirst, show],
  );

  /** The next page after the last row, with the filters in force. */
  const showMore = useCallback(() => {
    const { filters: current, cursor: after } = now.current;
    if (!after) return;
    const mine = generation.current;
    setFailure(null);
    setBusy(true);
    listThoughts(current, after).then(
      (list) => {
        if (mine !== generation.current) return;
        show([...(now.current.rows ?? []), ...list.items], list.next_cursor);
        setBusy(false);
      },
      (error: unknown) => fail(mine, error, "more"),
    );
  }, [fail, show]);

  /**
   * The shown rows again from the newest, as many as were shown and at least
   * a page, replaced at once; the old rows stay until then (decision 9).
   */
  const reload = useCallback(async () => {
    const mine = ++generation.current;
    const current = now.current.filters;
    const target = Math.max(now.current.rows?.length ?? 0, PAGE);
    setFailure(null);
    setBusy(true);
    const loaded: ThoughtRow[] = [];
    let after: string | null = null;
    try {
      do {
        const list = await listThoughts(current, after ?? undefined, Math.min(MOST, target - loaded.length));
        if (mine !== generation.current) return;
        loaded.push(...list.items);
        after = list.next_cursor;
      } while (after && loaded.length < target);
    } catch (error) {
      fail(mine, error, "reload");
      return;
    }
    show(loaded, after);
    setBusy(false);
  }, [fail, show]);

  // The first load, and the end of every request in flight on unmount.
  // The state starts as a first load in flight, so only the request is sent.
  useEffect(() => {
    fetchFirst(++generation.current, now.current.filters);
    return () => {
      generation.current += 1;
    };
  }, [fetchFirst]);

  // The sheet closed: an id went to null, never on open or on a second row.
  useEffect(() => {
    if (wasOpen.current && !openId) void reload();
    wasOpen.current = openId;
  }, [openId, reload]);

  // A change saved in the sheet, also after it closed.
  useEffect(() => {
    const onChange = () => void reload();
    window.addEventListener(THOUGHT_CHANGED_EVENT, onChange);
    return () => window.removeEventListener(THOUGHT_CHANGED_EVENT, onChange);
  }, [reload]);

  /** Changes one filter and lists again from the newest; an unset filter is left out. */
  function setFilter(change: ThoughtFilters) {
    const next: ThoughtFilters = { ...now.current.filters, ...change };
    for (const name of Object.keys(next) as (keyof ThoughtFilters)[]) {
      if (!next[name]) delete next[name];
    }
    loadFirst(next);
  }

  /** Applies the Tag field only when its trimmed text differs from the tag applied. */
  function applyTag() {
    const tag = tagText.trim();
    if (tag === (now.current.filters.tag ?? "")) return;
    setFilter({ tag: tag || undefined });
  }

  function onTagKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      applyTag();
    }
  }

  /** A day outside the server's range, such as a year typed in part, is not applied. */
  function changeDay(name: DateFilter, value: string) {
    setDayText((text) => ({ ...text, [name]: value }));
    const applied = now.current.filters[name] ?? "";
    if (value === "") {
      if (applied) setFilter({ [name]: undefined });
      return;
    }
    if (inRange(value) && value !== applied) setFilter({ [name]: value });
  }

  /** Repeats the request that failed: the same filters, and for "Show more" the same cursor. */
  function retry() {
    if (failure?.retry === "first") loadFirst(now.current.filters);
    else if (failure?.retry === "more") showMore();
    else void reload();
  }

  const filtered = hasFilter(filters);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
        <h1 className="text-lg font-semibold">Library</h1>
        <div className="flex flex-wrap items-end gap-3 text-sm" role="group" aria-label="Filters">
          <label className="flex flex-col gap-1">
            Category
            <select
              className="rounded-md border bg-background px-2 py-1"
              value={filters.category ?? ""}
              onChange={(event) => setFilter({ category: event.target.value || undefined })}
            >
              <option value="">Any category</option>
              {categories.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            Tag
            <input
              type="text"
              className="w-36 rounded-md border bg-background px-2 py-1"
              value={tagText}
              onChange={(event) => setTagText(event.target.value)}
              onKeyDown={onTagKey}
              onBlur={applyTag}
            />
          </label>
          <label className="flex flex-col gap-1">
            Status
            <select
              className="rounded-md border bg-background px-2 py-1"
              value={filters.status ?? ""}
              onChange={(event) =>
                setFilter({ status: (event.target.value || undefined) as ThoughtStatus | undefined })
              }
            >
              <option value="">Any status</option>
              {THOUGHT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABELS[status]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            Filed from
            <input
              type="date"
              className="rounded-md border bg-background px-2 py-1"
              min={FIRST_DAY}
              max={LAST_DAY}
              value={dayText.filed_from}
              onChange={(event) => changeDay("filed_from", event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            Filed to
            <input
              type="date"
              className="rounded-md border bg-background px-2 py-1"
              min={FIRST_DAY}
              max={LAST_DAY}
              value={dayText.filed_to}
              onChange={(event) => changeDay("filed_to", event.target.value)}
            />
          </label>
        </div>

        {failure && (
          <div className="flex flex-wrap items-center gap-2">
            <p role="alert" className="text-sm text-destructive">
              {failure.message}
            </p>
            <Button size="sm" variant="outline" onClick={retry}>
              Try again
            </Button>
          </div>
        )}
        {rows === null && busy && (
          <p role="status" className="text-sm text-muted-foreground">
            Loading thoughts…
          </p>
        )}
        {rows !== null && rows.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {filtered ? "No thoughts match these filters." : "No thoughts filed yet."}
          </p>
        )}
        {rows !== null && rows.length > 0 && (
          <ul aria-label="Thoughts" className="flex flex-col gap-1">
            {rows.map((row) => (
              <li key={row.id}>
                <Row row={row} />
              </li>
            ))}
          </ul>
        )}
        {rows !== null && cursor && (
          <div>
            <Button variant="outline" onClick={showMore} disabled={busy}>
              Show more
            </Button>
          </div>
        )}
      </div>
      <ThoughtSheet />
    </div>
  );
}

/** What a row shows under its title; a missing category, tag, date, or status leaves no element. */
function metaOf(row: ThoughtRow): ReactNode[] {
  const parts: ReactNode[] = [];
  if (row.category) parts.push(<Badge>{row.category}</Badge>);
  if (row.tags.length > 0) {
    parts.push(
      <span className="flex flex-wrap gap-1">
        {row.tags.map((tag, index) => (
          <Fragment key={tag}>
            {index > 0 && " "}
            <Badge variant="outline">#{tag}</Badge>
          </Fragment>
        ))}
      </span>,
    );
  }
  parts.push(<span>{filedDay(row.created_at)}</span>);
  if (row.when) parts.push(<span>{formatWhen(row.when)}</span>);
  // Any status but open shows its label, so a later one never looks open (decision 7).
  if (row.status !== "open") parts.push(<Badge variant="secondary">{STATUS_LABELS[row.status]}</Badge>);
  return parts;
}

/**
 * One thought. The button is named by the title alone and described by the
 * rest, so a screen reader hears the title first and then the badges and
 * dates (design decision 1).
 */
function Row({ row }: { row: ThoughtRow }) {
  const id = useId();
  const titleId = `${id}-title`;
  const metaId = `${id}-meta`;
  return (
    <button
      type="button"
      aria-labelledby={titleId}
      aria-describedby={metaId}
      onClick={() => openThought(row.id)}
      className="flex w-full flex-col gap-1 rounded-lg border px-3 py-2 text-left text-sm hover:bg-muted"
    >
      <span id={titleId} className="font-medium">
        {row.title}
      </span>
      <span id={metaId} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        {metaOf(row).map((part, index) => (
          // A space between parts, so the description reads as separate words.
          <Fragment key={index}>
            {index > 0 && " "}
            {part}
          </Fragment>
        ))}
      </span>
    </button>
  );
}
