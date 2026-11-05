"use client";

// The Upcoming page: the user's dated thoughts from the browser's today on,
// grouped by day (thought-dates design decision 8). An item opens the thought
// in the side sheet over the list; the list loads again when the sheet closes
// or a thought changes, so an edit or a delete shows.
import { useCallback, useEffect, useRef, useState } from "react";

import { ThoughtSheet } from "@/components/chat/thought-sheet";
import { Badge } from "@/components/ui/badge";
import { UnauthenticatedError } from "@/lib/api";
import { dayHeading, formatPoint, localToday, splitPoint, type When } from "@/lib/dates";
import { redirectToLogin } from "@/lib/redirect-to-login";
import { openThought, useOpenThought } from "@/lib/thought-link";
import { getUpcoming, THOUGHT_CHANGED_EVENT, type Upcoming, type UpcomingItem } from "@/lib/thoughts";

type Loaded =
  | { state: "loading" }
  | { state: "ready"; today: string; upcoming: Upcoming }
  | { state: "failed" };

type Day = { day: string; items: UpcomingItem[] };

/** The items by day, in their order; one that started before today goes under today. */
export function byDay(items: UpcomingItem[], today: string): Day[] {
  const days: Day[] = [];
  for (const item of items) {
    const start = splitPoint(item.when.start).day;
    const day = start < today ? today : start;
    const last = days.at(-1);
    if (last?.day === day) last.items.push(item);
    else days.push({ day, items: [item] });
  }
  return days;
}

/**
 * What an item shows beside its title: its end when it spans days ("until Fri
 * 2 Oct" or "until Fri 2 Oct, 10:00"), else its time ("19:00", or "09:30 –
 * 11:00"), else nothing.
 */
export function itemTime(when: When): string {
  const start = splitPoint(when.start);
  const end = when.end ? splitPoint(when.end) : null;
  if (end && end.day !== start.day) return `until ${formatPoint(when.end!, { year: false })}`;
  if (!start.time) return "";
  return end?.time ? `${start.time} – ${end.time}` : start.time;
}

export function UpcomingList() {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const openId = useOpenThought();
  const wasOpen = useRef(openId);
  // Only the latest load may answer, so a slow earlier one never wins.
  const loads = useRef(0);

  const load = useCallback(() => {
    const mine = ++loads.current;
    const today = localToday();
    getUpcoming(today)
      .then((upcoming) => mine === loads.current && setLoaded({ state: "ready", today, upcoming }))
      .catch((error: unknown) => {
        if (error instanceof UnauthenticatedError) {
          redirectToLogin(window.location.pathname + window.location.search);
          return;
        }
        if (mine === loads.current) setLoaded({ state: "failed" });
      });
  }, []);

  // The first load, as the page opens.
  useEffect(load, [load]);

  // The sheet closed: an edit or delete there shows now.
  useEffect(() => {
    if (wasOpen.current && !openId) load();
    wasOpen.current = openId;
  }, [openId, load]);

  useEffect(() => {
    window.addEventListener(THOUGHT_CHANGED_EVENT, load);
    return () => window.removeEventListener(THOUGHT_CHANGED_EVENT, load);
  }, [load]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-6">
        <h1 className="text-lg font-semibold">Upcoming</h1>
        {loaded.state === "loading" && <p className="text-sm text-muted-foreground">Loading…</p>}
        {loaded.state === "failed" && (
          <p role="alert" className="text-sm text-destructive">
            The list could not be loaded. Try again.
          </p>
        )}
        {loaded.state === "ready" && loaded.upcoming.items.length === 0 && (
          <p className="text-sm text-muted-foreground">Nothing is coming up.</p>
        )}
        {loaded.state === "ready" &&
          byDay(loaded.upcoming.items, loaded.today).map(({ day, items }) => {
            const heading = dayHeading(day, loaded.today);
            return (
              <section key={day} aria-label={heading} className="flex flex-col gap-2">
                <h2 className="text-sm font-medium text-muted-foreground">{heading}</h2>
                <ul className="flex flex-col gap-1">
                  {items.map((item) => (
                    <li key={item.id}>
                      <Item item={item} />
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        {loaded.state === "ready" && loaded.upcoming.more && (
          <p className="text-sm text-muted-foreground">
            More dated thoughts are coming up than this page shows.
          </p>
        )}
      </div>
      <ThoughtSheet />
    </div>
  );
}

function Item({ item }: { item: UpcomingItem }) {
  const time = itemTime(item.when);
  return (
    <button
      type="button"
      onClick={() => openThought(item.id)}
      className="flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left text-sm hover:bg-muted"
    >
      {time && <span className="shrink-0 tabular-nums text-muted-foreground">{time}</span>}
      <span className="min-w-0 flex-1 truncate font-medium">{item.title}</span>
      {item.category && <Badge variant="outline">{item.category}</Badge>}
    </button>
  );
}
