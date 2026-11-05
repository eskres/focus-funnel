"use client";

// A thought's own date as fields, shared by the thought sheet's edit mode and
// (with thought-dates task 5.2) the proposal card (design decision 6). Native
// date and time inputs, so no picker dependency. The browser does not check
// the range itself: the server's refusal naming `when` shows in the caller's
// alert, and the fields keep what the user typed.
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { localToday, splitPoint, type When } from "@/lib/dates";

/** The date as the user edits it: "" for an empty field, and no end when `end` is "". */
export type DateText = { start: string; startTime: string; end: string; endTime: string };

/** The fields for a stored date, or null (the "Add date" button) for none. */
export function dateTextOf(when: When | null | undefined): DateText | null {
  if (!when) return null;
  const start = splitPoint(when.start);
  const end = when.end ? splitPoint(when.end) : { day: "", time: "" };
  return { start: start.day, startTime: start.time, end: end.day, endTime: end.time };
}

const point = (day: string, time: string) => (time ? `${day}T${time}` : day);

/** The `when` to send for the fields, with the browser's zone; null for no date. */
export function whenOfText(text: DateText | null, timeZone: string): When | null {
  if (!text) return null;
  return {
    start: point(text.start, text.startTime),
    end: text.end ? point(text.end, text.startTime ? text.endTime : "") : null,
    time_zone: timeZone,
  };
}

/** Whether two dates are the same day and time, whatever zone each was set in. */
export function sameWhen(a: When | null | undefined, b: When | null | undefined): boolean {
  if (!a || !b) return !a && !b;
  return a.start === b.start && (a.end ?? null) === (b.end ?? null);
}

/**
 * No date: an "Add date" button. A date: the start day, an optional start
 * time, "Clear date", and "Add end". An end: its day, and its time only when
 * the start has one; the end time starts as the start time, so both or
 * neither have a time.
 */
export function DateFields({
  value,
  onChange,
  disabled,
}: {
  value: DateText | null;
  onChange: (next: DateText | null) => void;
  disabled?: boolean;
}) {
  if (!value) {
    return (
      <div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={() => onChange({ start: localToday(), startTime: "", end: "", endTime: "" })}
        >
          Add date
        </Button>
      </div>
    );
  }

  function setStartTime(startTime: string) {
    if (!value) return;
    const endTime = !value.end || !startTime ? "" : value.endTime || startTime;
    onChange({ ...value, startTime, endTime });
  }

  return (
    <fieldset className="flex flex-col gap-2" disabled={disabled}>
      <legend className="mb-1 text-xs font-medium">Date</legend>
      <div className="flex flex-wrap gap-2">
        <Label className="flex flex-col items-start gap-1 text-xs">
          Start date
          <Input
            type="date"
            value={value.start}
            onChange={(event) => onChange({ ...value, start: event.target.value })}
          />
        </Label>
        <Label className="flex flex-col items-start gap-1 text-xs">
          Start time
          <Input type="time" value={value.startTime} onChange={(event) => setStartTime(event.target.value)} />
        </Label>
      </div>
      {value.end && (
        <div className="flex flex-wrap gap-2">
          <Label className="flex flex-col items-start gap-1 text-xs">
            End date
            <Input
              type="date"
              value={value.end}
              onChange={(event) => onChange({ ...value, end: event.target.value })}
            />
          </Label>
          {value.startTime && (
            <Label className="flex flex-col items-start gap-1 text-xs">
              End time
              <Input
                type="time"
                value={value.endTime}
                onChange={(event) => onChange({ ...value, endTime: event.target.value })}
              />
            </Label>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {value.end ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onChange({ ...value, end: "", endTime: "" })}
          >
            Remove end
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onChange({ ...value, end: value.start, endTime: value.startTime })}
          >
            Add end
          </Button>
        )}
        <Button type="button" size="sm" variant="outline" onClick={() => onChange(null)}>
          Clear date
        </Button>
      </div>
    </fieldset>
  );
}
