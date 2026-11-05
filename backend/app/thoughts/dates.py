"""A thought's date: the `when` shape on the wire, and the columns it is stored in.

`when` is `{"start": ..., "end": ..., "time_zone": ...}` or null for no date.
`start` and `end` are `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`, the user's wall time
with no offset. The date is stored as written, in five columns, with the zone
it was set in (thought-dates design decisions 1 and 2). A refused date names
the field `when`. A missing or unknown zone is stored as `UTC`, never refused.
"""

import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.errors import ApiError, ErrorCode

FIELD = "when"
DEFAULT_ZONE = "UTC"
FORMAT = "YYYY-MM-DD or YYYY-MM-DDTHH:MM"
# Checked before parsing: date.fromisoformat also takes "20261002" and "2026-W40-5".
_POINT = re.compile(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}):(\d{2}))?")


def _refused(message: str) -> ApiError:
    return ApiError(422, ErrorCode.VALIDATION_ERROR, f"{FIELD}: {message}")


@dataclass(frozen=True)
class DateColumns:
    """The five Thought columns for one date; all None for no date."""

    starts_on: date | None = None
    starts_at: time | None = None
    ends_on: date | None = None
    ends_at: time | None = None
    time_zone: str | None = None

    def values(self) -> dict[str, Any]:
        """As keyword arguments for Thought, or for setting its attributes."""
        return asdict(self)


NO_DATE = DateColumns()


def zone_from(name: Any) -> ZoneInfo:
    """The IANA zone with this name, or UTC for a missing or unknown one."""
    if isinstance(name, str) and name.strip():
        try:
            return ZoneInfo(name.strip())
        except (ZoneInfoNotFoundError, ValueError, TypeError, OSError):
            pass
    return ZoneInfo(DEFAULT_ZONE)


def utc_now() -> datetime:
    """The current time. Tests replace it to fix "today"."""
    return datetime.now(UTC)


def today_in(zone: ZoneInfo) -> date:
    """The user's local date in that zone."""
    return utc_now().astimezone(zone).date()


def _point(value: Any, side: str) -> tuple[date, time | None]:
    if not isinstance(value, str):
        raise _refused(f"the {side} must be written {FORMAT}")
    match = _POINT.fullmatch(value.strip())
    if match is None:
        raise _refused(f"the {side} must be written {FORMAT}")
    day, hour, minute = match.groups()
    try:
        on = date.fromisoformat(day)
        at = time(int(hour), int(minute)) if hour is not None else None
    except ValueError:
        raise _refused(f"the {side} is not a real date or time") from None
    return on, at


def parse_when(value: Any) -> DateColumns:
    """The columns for a `when` value, or NO_DATE for null. Raises validation_error naming `when`.

    A date needs a start; the start and end both have a time or neither does;
    the end is not before the start.
    """
    if value is None:
        return NO_DATE
    if not isinstance(value, dict):
        raise _refused("must be an object with a start and an optional end, or null")
    if value.get("start") is None:
        raise _refused("a date needs a start")
    starts_on, starts_at = _point(value["start"], "start")
    ends_on = ends_at = None
    if value.get("end") is not None:
        ends_on, ends_at = _point(value["end"], "end")
        if (starts_at is None) != (ends_at is None):
            raise _refused("the start and the end must both have a time or both have none")
        if (ends_on, ends_at or time()) < (starts_on, starts_at or time()):
            raise _refused("the end must not be before the start")
    return DateColumns(
        starts_on=starts_on,
        starts_at=starts_at,
        ends_on=ends_on,
        ends_at=ends_at,
        time_zone=zone_from(value.get("time_zone")).key,
    )


def _written(on: date, at: time | None) -> str:
    return on.isoformat() if at is None else f"{on.isoformat()}T{at.strftime('%H:%M')}"


def when_of(row: Any) -> dict[str, str | None] | None:
    """The `when` value of a Thought (or DateColumns), or None when it has no date."""
    if row.starts_on is None:
        return None
    return {
        "start": _written(row.starts_on, row.starts_at),
        "end": _written(row.ends_on, row.ends_at) if row.ends_on is not None else None,
        "time_zone": row.time_zone or DEFAULT_ZONE,
    }
