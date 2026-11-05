// The browser's zone on the requests that need it, and a stored day shown as
// written in a zone west of UTC (thought-dates task 5.1).
import { afterAll, afterEach, describe, expect, it, vi } from "vitest";

import { fakeApi, json } from "@/test/fake-api";

import { streamChat } from "./chat";
import { offerProposal } from "./conversations";
import { formatDay, formatWhen, localToday } from "./dates";
import { browserTimeZone } from "./time-zone";

// Set before any date is read, so this file runs as a browser in California.
const zoneBefore = process.env.TZ;
process.env.TZ = "America/Los_Angeles";

afterEach(() => {
  vi.unstubAllGlobals();
});

afterAll(() => {
  if (zoneBefore === undefined) delete process.env.TZ;
  else process.env.TZ = zoneBefore;
});

async function drain(iterator: AsyncGenerator<unknown>) {
  for await (const event of iterator) void event;
}

describe("the browser's zone", () => {
  it("is the zone the browser runs in", () => {
    expect(browserTimeZone()).toBe("America/Los_Angeles");
  });

  it("goes with every chat message", async () => {
    const { calls } = fakeApi({ "POST /api/chat": new Response("event: done\ndata: {}\n\n") });

    await drain(streamChat({ message: "dinner with Sam Friday at 7", conversationId: "c1" }));

    expect(calls[0].body).toEqual({
      message: "dinner with Sam Friday at 7",
      conversation_id: "c1",
      time_zone: "America/Los_Angeles",
    });
  });

  it("goes with the offer of the held proposal before archive or /compact", async () => {
    const { calls } = fakeApi({ "POST /api/conversations/c1/proposal": json(200, { proposal: null }) });

    expect(await offerProposal("c1")).toBeNull();

    expect(calls).toEqual([
      {
        method: "POST",
        path: "/api/conversations/c1/proposal",
        body: { time_zone: "America/Los_Angeles" },
      },
    ]);
  });
});

describe("a stored day west of UTC", () => {
  it("shows 2026-10-02 as 2 October, not the day before", () => {
    // What the formatter must not do: a date string parses as UTC midnight.
    expect(new Date("2026-10-02").getDate()).toBe(1);

    expect(formatDay("2026-10-02")).toBe("Fri 2 Oct 2026");
    expect(formatWhen({ start: "2026-10-02", end: null, time_zone: "Europe/Oslo" })).toBe("Fri 2 Oct 2026");
    expect(formatWhen({ start: "2026-10-02T19:00", end: null, time_zone: "Europe/Oslo" })).toBe(
      "Fri 2 Oct 2026, 19:00",
    );
    expect(formatWhen({ start: "2026-11-03", end: "2026-11-06", time_zone: "UTC" })).toBe(
      "Tue 3 Nov 2026 – Fri 6 Nov 2026",
    );
  });

  it("takes today from the browser's local clock", () => {
    // 05:00 UTC on 2 October is still 1 October in California.
    expect(localToday(new Date("2026-10-02T05:00:00Z"))).toBe("2026-10-01");
  });
});
