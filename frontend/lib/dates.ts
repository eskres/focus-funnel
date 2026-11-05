// A thought's own date, `when`, as the server sends and takes it (thought-dates
// design decision 2), and how it reads on screen.
//
// `start` and `end` are the user's wall time, `YYYY-MM-DD` or
// `YYYY-MM-DDTHH:MM`, and show as written: the strings are split, never parsed
// with `new Date("2026-10-02")`, which reads as UTC midnight and shows the day
// before west of UTC.

/** A thought's date: start, optional end, and the zone it was set in. */
export type When = { start: string; end: string | null; time_zone: string };

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A `YYYY-MM-DD[THH:MM]` string as its day and its time ("" for none). */
export function splitPoint(point: string): { day: string; time: string } {
  const [day, time = ""] = point.split("T");
  return { day, time };
}

function dayParts(day: string): { year: number; month: number; date: number; weekday: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return null;
  const [year, month, date] = match.slice(1).map(Number);
  // UTC on both sides, so the browser's zone never moves the day.
  const weekday = new Date(Date.UTC(year, month - 1, date)).getUTCDay();
  return { year, month, date, weekday };
}

/** How a date reads: with its year (the sheet), or without (a date choice on a card). */
type Style = { year?: boolean };

/** "Fri 2 Oct 2026" for "2026-10-02" ("Fri 2 Oct" with no year); the text as it is when it is not a day. */
export function formatDay(day: string, { year = true }: Style = {}): string {
  const parts = dayParts(day);
  if (!parts) return day;
  const short = `${WEEKDAYS[parts.weekday]} ${parts.date} ${MONTHS[parts.month - 1]}`;
  return year ? `${short} ${parts.year}` : short;
}

/** "Fri 2 Oct 2026, 19:00", or "Fri 2 Oct 2026" for a day with no time. */
export function formatPoint(point: string, style: Style = {}): string {
  const { day, time } = splitPoint(point);
  return time ? `${formatDay(day, style)}, ${time}` : formatDay(day, style);
}

/**
 * The whole date: "Fri 2 Oct 2026, 19:00", "Tue 3 Nov 2026 – Fri 6 Nov 2026",
 * or "Mon 5 Oct 2026, 09:30 – 11:00" for an end later the same day.
 */
export function formatWhen(when: When, style: Style = {}): string {
  const start = formatPoint(when.start, style);
  if (!when.end) return start;
  const end = splitPoint(when.end);
  if (end.day === splitPoint(when.start).day && end.time) return `${start} – ${end.time}`;
  return `${start} – ${formatPoint(when.end, style)}`;
}

/** The browser's local date now, as `YYYY-MM-DD`. */
export function localToday(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const LONG_WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const LONG_MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** The day `count` days after a `YYYY-MM-DD` day, counted on the calendar alone. */
export function addDays(day: string, count: number): string {
  const parts = dayParts(day);
  if (!parts) return day;
  const moved = new Date(Date.UTC(parts.year, parts.month - 1, parts.date + count));
  return moved.toISOString().slice(0, 10);
}

/**
 * A day's heading on the Upcoming page: "Today", "Tomorrow", or "Monday 5
 * October", with the year only when it is not this year's.
 */
export function dayHeading(day: string, today: string): string {
  if (day === today) return "Today";
  if (day === addDays(today, 1)) return "Tomorrow";
  const parts = dayParts(day);
  if (!parts) return day;
  const heading = `${LONG_WEEKDAYS[parts.weekday]} ${parts.date} ${LONG_MONTHS[parts.month - 1]}`;
  return day.slice(0, 4) === today.slice(0, 4) ? heading : `${heading} ${parts.year}`;
}
