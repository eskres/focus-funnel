// The browser's IANA time zone, sent with a date the user sets so the server
// stores the zone it was set in (thought-dates design decision 3).

/** The browser's zone, such as "Europe/Oslo"; "UTC" when the browser names none. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
