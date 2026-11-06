"""Exporting all of a user's thoughts as one JSON or Markdown file
(thought-export design decisions 2 to 8, 12, 15, and 16).

The thoughts are read in keyset batches, each in its own short session, and
written as they arrive, so memory stays flat as the store grows. A lease per
export keeps one export per user and format running at a time; a delete of
the user's content or account, or the end of a demo session, stops it.

This module never imports app.demo at the top: app.demo imports
app.user_data, which calls stop_exports() (design decision 16).
"""

import logging
import re
import time
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.errors import export_running, too_many_exports
from app.models import Conversation, Proposal, Thought, ThoughtAddition
from app.routers.thoughts import AdditionOut, ThoughtOut, addition_view, thought_view
from app.thoughts.store import ThoughtOrigin

logger = logging.getLogger(__name__)

# Thoughts per batch, and leases a user may hold at once. Read at call time,
# so tests can lower them.
EXPORT_BATCH = 200
EXPORT_LIVE_LIMIT = 4
# A lease not written for this long is stale: it no longer counts as running.
STALE_SECONDS = 60

FORMATS = ("json", "markdown")


def utcnow() -> datetime:
    """The export's start; tests replace it (design decision 6)."""
    return datetime.now(UTC)


def monotonic() -> float:
    """The lease clock; tests move it, so it is read through the module."""
    return time.monotonic()


class ExportAborted(Exception):
    """The export was stopped by a delete or by the demo session's end."""


@dataclass(eq=False)
class Lease:
    """One export that has not ended. Compared by identity (design decision 7)."""

    user_id: uuid.UUID
    format: str
    # The monotonic time of its last write.
    written_at: float
    # The demo session's end, aware, for a demo user; else None.
    expires_at: datetime | None = None
    aborted: bool = False

    def running(self, now: float) -> bool:
        return not self.aborted and now - self.written_at < STALE_SECONDS

    def touch(self) -> None:
        self.written_at = monotonic()

    def check(self) -> None:
        """Raise ExportAborted once the export was stopped or the demo session ended."""
        # Imported here: app.demo imports app.user_data, which imports this
        # module (design decision 16). Read through the module, so a test that
        # patches app.demo.now is seen.
        from app import demo

        if self.aborted:
            raise ExportAborted()
        if self.expires_at is not None and demo.now() >= self.expires_at:
            raise ExportAborted()


# Every lease not yet released, stale ones included, by user.
LIVE: dict[uuid.UUID, set[Lease]] = {}


def take_lease(user_id: uuid.UUID, format: str, expires_at: datetime | None) -> Lease:
    """Check the user's leases and add a new one, in one synchronous step.

    Refuses with 409 export_running when the user already holds
    EXPORT_LIVE_LIMIT leases, or a running lease of this format.
    """
    leases = LIVE.get(user_id, set())
    now = monotonic()
    if len(leases) >= EXPORT_LIVE_LIMIT:
        raise too_many_exports()
    if any(lease.format == format and lease.running(now) for lease in leases):
        raise export_running()
    lease = Lease(user_id=user_id, format=format, written_at=now, expires_at=expires_at)
    LIVE.setdefault(user_id, set()).add(lease)
    return lease


def release(lease: Lease) -> None:
    """Remove this lease, and only this one; drop the user's key once empty."""
    leases = LIVE.get(lease.user_id)
    if leases is None:
        return
    leases.discard(lease)
    if not leases:
        LIVE.pop(lease.user_id, None)


def stop_exports(user_id: uuid.UUID) -> None:
    """Stop every export of the user, in both formats, stale ones included
    (design decision 15). Waits for nothing."""
    for lease in LIVE.get(user_id, ()):
        lease.aborted = True


async def additions_for(
    session: AsyncSession, user_id: uuid.UUID, thought_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[AdditionOut]]:
    """The additions of these thoughts, newest first, by thought id, each with
    its conversation's current title. Only the owner's conversations are
    joined, so an addition whose conversation was deleted is not listed. The
    addition's `before` is never read."""
    rows = await session.execute(
        select(
            ThoughtAddition.id,
            ThoughtAddition.thought_id,
            ThoughtAddition.added_at,
            ThoughtAddition.undone_at.is_not(None).label("undone"),
            ThoughtAddition.proposal_id,
            Conversation.id.label("conversation_id"),
            Conversation.title.label("conversation_title"),
        )
        .join(Proposal, Proposal.id == ThoughtAddition.proposal_id)
        .join(
            Conversation,
            (Conversation.id == Proposal.conversation_id)
            & (Conversation.user_id == user_id),
        )
        .where(
            ThoughtAddition.thought_id.in_(thought_ids),
            ThoughtAddition.user_id == user_id,
        )
        .order_by(ThoughtAddition.added_at.desc(), ThoughtAddition.to_position.desc())
    )
    found: dict[uuid.UUID, list[AdditionOut]] = {}
    for row in rows:
        found.setdefault(row.thought_id, []).append(addition_view(row))
    return found


def _thoughts_query(user_id: uuid.UUID, after: tuple[datetime, uuid.UUID] | None):
    """One batch of the user's thoughts with their origin, oldest first, after
    the last one read (design decision 2)."""
    query = (
        select(
            Thought,
            Proposal.created_at.label("proposed_at"),
            Conversation.id.label("conversation_id"),
            Conversation.title.label("conversation_title"),
            Conversation.archived_at.label("archived_at"),
        )
        .outerjoin(Proposal, Proposal.id == Thought.proposal_id)
        .outerjoin(
            Conversation,
            (Conversation.id == Proposal.conversation_id)
            & (Conversation.user_id == user_id),
        )
        .where(Thought.user_id == user_id)
        .order_by(Thought.created_at, Thought.id)
        .limit(EXPORT_BATCH)
    )
    if after is not None:
        created_at, last_id = after
        # The plain range gives the planner a range on the index rather than
        # an OR alone, as thought-library's list does.
        query = query.where(
            Thought.created_at >= created_at,
            or_(Thought.created_at > created_at, Thought.id > last_id),
        )
    return query


def _origin(row: Any) -> ThoughtOrigin | None:
    if row.conversation_id is None:
        return None
    return ThoughtOrigin(
        conversation_id=row.conversation_id,
        conversation_title=row.conversation_title,
        archived=row.archived_at is not None,
        proposal_id=row.Thought.proposal_id,
        proposed_at=row.proposed_at,
    )


async def export_thoughts(
    session_factory: Callable[[], AsyncSession], user_id: uuid.UUID, lease: Lease
) -> AsyncIterator[list[ThoughtOut]]:
    """The user's thoughts in batches of EXPORT_BATCH, oldest first, each
    batch read in its own session at REPEATABLE READ on Postgres. Never yields
    an empty batch. Checks the lease before and after each thoughts query and
    once more after the last batch (design decisions 2 and 15)."""
    after: tuple[datetime, uuid.UUID] | None = None
    while True:
        lease.check()
        async with session_factory() as session:
            if session.get_bind().dialect.name == "postgresql":
                # Both queries of the batch read one snapshot.
                await session.connection(
                    execution_options={"isolation_level": "REPEATABLE READ"}
                )
            rows = (await session.execute(_thoughts_query(user_id, after))).all()
            lease.check()
            if not rows:
                return
            additions = await additions_for(
                session, user_id, [row.Thought.id for row in rows]
            )
            batch = [
                thought_view(
                    row.Thought, _origin(row), additions.get(row.Thought.id, [])
                )
                for row in rows
            ]
            last = rows[-1].Thought
            after = (last.created_at, last.id)
            full = len(rows) >= EXPORT_BATCH
            # Hold one batch at a time: drop the rows before the next is read.
            del rows, additions, last
        yield batch
        del batch
        if not full:
            lease.check()
            return


def _exported_at(moment: datetime) -> str:
    return _utc(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(moment: datetime) -> datetime:
    """SQLite hands back naive times; they were stored as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


async def json_chunks(
    batches: AsyncIterable[list[ThoughtOut]], exported_at: datetime
) -> AsyncIterator[str]:
    """One JSON document, one thought per line, the count last (design
    decision 4). The opening line comes before the first batch is asked for,
    and an empty batch writes nothing."""
    yield (
        '{"format":"focus-funnel-thoughts","version":1,'
        f'"exported_at":"{_exported_at(exported_at)}","thoughts":['
    )
    count = 0
    async for batch in batches:
        if not batch:
            continue
        body = ",\n".join(thought.model_dump_json() for thought in batch)
        yield ("\n" if count == 0 else ",\n") + body
        count += len(batch)
    yield ("\n]" if count else "]") + f',"count":{count}}}\n'


# Markdown (design decision 5).

_ESCAPED = set("\\`*_[]<>!#&~|")

# A bare web address as autolinking viewers find one in the source (GFM's
# extended autolinks, markdown-it's linkify): a scheme with `://`, or `www.`,
# up to the next space or `<`. Matching more than a viewer links is safe, since
# only characters that are inert in CommonMark are left unescaped (decision 30).
_ADDRESS = re.compile(r"(?:(?:https?|ftp)://|www\.)[^\s<]*", re.IGNORECASE)
_ENTITY = re.compile(
    r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});"
)


def _escape_all(text: str) -> str:
    return "".join("\\" + char if char in _ESCAPED else char for char in text)


def _inert_in_address(address: str, at: int) -> bool:
    """Whether the escaped character at `at` inside an address can be left as
    it is: an autolinking viewer shows a backslash there and puts it in the
    link, while a CommonMark viewer reads the bare character as plain text
    (design decision 30)."""
    char = address[at]
    if char in "#!|":
        # `#` never opens a line here, `!` makes an image only before an
        # (escaped) `[`, and a table's delimiter row cannot hold an address.
        return True
    if char == "&":
        return _ENTITY.match(address, at) is None
    if char == "~":
        # A lone `~` strikes nothing in markdown-it, which needs `~~`.
        return address[at - 1 : at] != "~" and address[at + 1 : at + 2] != "~"
    if char == "_":
        # A run of `_` between two letters or digits cannot open or close
        # emphasis.
        start, end = at, at
        while start > 0 and address[start - 1] == "_":
            start -= 1
        while end < len(address) and address[end] == "_":
            end += 1
        return (
            start > 0
            and end < len(address)
            and address[start - 1].isalnum()
            and address[end].isalnum()
        )
    return False


def _escape_address(address: str) -> str:
    return "".join(
        "\\" + char if char in _ESCAPED and not _inert_in_address(address, at) else char
        for at, char in enumerate(address)
    )


def _escape_chars(text: str) -> str:
    parts: list[str] = []
    last = 0
    for found in _ADDRESS.finditer(text):
        parts.append(_escape_all(text[last : found.start()]))
        parts.append(_escape_address(found.group()))
        last = found.end()
    parts.append(_escape_all(text[last:]))
    return "".join(parts)


def _escape_line_start(line: str) -> str:
    """Escape a list marker, rule, or setext underline at the line's start,
    where the start is its first character that is not a space or a tab."""
    body = line.lstrip(" \t")
    lead = line[: len(line) - len(body)]
    if not body:
        return line
    if body[0] in "-+=":
        return f"{lead}\\{body}"
    digits = len(body) - len(body.lstrip("0123456789"))
    if digits and digits < len(body) and body[digits] in ".)":
        return f"{lead}{body[:digits]}\\{body[digits:]}"
    return line


def _escape(line: str) -> str:
    """One line of data, shown as plain text."""
    return _escape_line_start(_escape_chars(line))


def _one_line(text: str) -> str:
    """A single-line field with every line break a space, escaped."""
    return _escape(" ".join(text.splitlines()))


def _quote_line(line: str) -> str:
    """One summary line in the block quote. Leading whitespace that holds a
    tab or reaches four spaces starts with a character reference, so the
    line never becomes an indented code block."""
    if not line:
        return ">"
    body = line.lstrip(" \t")
    lead = line[: len(line) - len(body)]
    escaped = _escape_line_start(lead + _escape_chars(body))
    if "\t" in lead or lead.count(" ") >= 4:
        escaped = ("&#9;" if lead[0] == "\t" else "&#32;") + escaped[1:]
    return f"> {escaped}"


def _time(moment: datetime) -> str:
    return _utc(moment).strftime("%Y-%m-%d %H:%M") + " UTC"


def _status_line(thought: ThoughtOut) -> str:
    changed = thought.status_changed_at
    if changed is None:
        return f"- Status: {_one_line(thought.status)}"
    if thought.status == "done":
        how = "marked done"
    elif thought.status == "open":
        how = "reopened"
    else:
        how = "since"
    return f"- Status: {_one_line(thought.status)}, {how} {_time(changed)}"


def _date_line(when: dict[str, str | None]) -> str:
    text = (when["start"] or "").replace("T", " ")
    if when.get("end"):
        text += " to " + when["end"].replace("T", " ")
    if when.get("time_zone"):
        text += f" ({_one_line(when['time_zone'])})"
    return f"- Date: {text}"


def _tag(tag: str) -> str:
    """One tag as a code span, so a viewer shows it as stored and it reads as
    one tag, a `, #` inside it included (design decision 31). The fence is one
    backtick longer than the longest run in the tag; a tag that ends with a
    backtick gets a space on each side, which the viewer drops."""
    body = "#" + " ".join(tag.splitlines())
    longest = run = 0
    for char in body:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    fence = "`" * (longest + 1)
    if body.endswith("`"):
        body = f" {body} "
    return f"{fence}{body}{fence}"


def _fence(raw_text: str) -> str:
    longest = run = 0
    for char in raw_text:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


def _section(thought: ThoughtOut) -> str:
    lines = [f"## {_one_line(thought.title)}", "", _status_line(thought)]
    if thought.category:
        lines.append(f"- Category: {_one_line(thought.category)}")
    if thought.tags:
        lines.append("- Tags: " + ", ".join(_tag(tag) for tag in thought.tags))
    if thought.when:
        lines.append(_date_line(thought.when))
    lines.append(f"- Filed: {_time(thought.created_at)}")
    lines.append(f"- Changed: {_time(thought.updated_at)}")
    origin = thought.origin
    if origin is not None:
        archived = " (archived)" if origin.archived else ""
        lines.append(
            f"- From: {_one_line(origin.conversation_title)}{archived}, "
            f"proposed {_time(origin.proposed_at)}, conversation {origin.conversation_id}, "
            f"proposal {origin.proposal_id}"
        )
    lines.append(f"- ID: {thought.id}")
    lines += ["", "### Summary", ""]
    lines += [_quote_line(line) for line in thought.summary.splitlines()] or [">"]
    text = "\n".join(lines) + "\n"
    if thought.raw_text is not None and thought.raw_text != "":
        fence = _fence(thought.raw_text)
        # The raw text exactly as given, then one \n, then the closing fence.
        text += f"\n### Raw text\n\n{fence}text\n{thought.raw_text}\n{fence}\n"
    if thought.additions:
        text += "\n### Additions\n\n"
        for addition in thought.additions:
            undone = " (undone)" if addition.undone else ""
            text += (
                f"- {_time(addition.added_at)} from {_one_line(addition.conversation_title)}, "
                f"conversation {addition.conversation_id}, proposal {addition.proposal_id}{undone}\n"
            )
    return text + "\n---\n\n"


async def markdown_chunks(
    batches: AsyncIterable[list[ThoughtOut]], exported_at: datetime
) -> AsyncIterator[str]:
    """One Markdown file, a section per thought, the end line last (design
    decision 5). An empty batch writes nothing."""
    yield f"# Focus Funnel thoughts\n\nExported {_time(exported_at)}.\n\n---\n\n"
    count = 0
    async for batch in batches:
        if not batch:
            continue
        yield "".join(_section(thought) for thought in batch)
        count += len(batch)
    if count == 0:
        yield "No thoughts.\n\n---\n\nEnd of export: 0 thoughts.\n"
    else:
        yield f"End of export: {count} thought{'' if count == 1 else 's'}.\n"


WRITERS = {"json": json_chunks, "markdown": markdown_chunks}
MEDIA_TYPES = {
    "json": "application/json; charset=utf-8",
    "markdown": "text/markdown; charset=utf-8",
}
EXTENSIONS = {"json": "json", "markdown": "md"}


class ExportResponse(StreamingResponse):
    """The streamed file. Its `__call__` always closes the generator, releases
    the lease, and logs one end line (design decisions 7 and 8)."""

    def __init__(
        self,
        lease: Lease,
        batches: AsyncIterator[list[ThoughtOut]],
        exported_at: datetime,
    ) -> None:
        self.lease = lease
        self.format = lease.format
        self.thoughts = 0
        self.finished = False
        filename = f"focus-funnel-thoughts-{_utc(exported_at).date().isoformat()}.{EXTENSIONS[self.format]}"
        super().__init__(
            self._body(batches, exported_at),
            media_type=MEDIA_TYPES[self.format],
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    async def _counted(
        self, batches: AsyncIterator[list[ThoughtOut]]
    ) -> AsyncIterator[list[ThoughtOut]]:
        async with aclosing(batches) as source:
            async for batch in source:
                self.thoughts += len(batch)
                yield batch

    async def _body(
        self, batches: AsyncIterator[list[ThoughtOut]], exported_at: datetime
    ) -> AsyncIterator[str]:
        # aclosing at each layer: closing an outer generator does not close
        # the ones it iterates, so the export's own finally runs at once.
        async with aclosing(self._counted(batches)) as counted:
            async with aclosing(WRITERS[self.format](counted, exported_at)) as chunks:
                async for chunk in chunks:
                    yield chunk
                    # The chunk was sent: the heartbeat (design decision 7).
                    self.lease.touch()
        self.finished = True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        outcome = "client_gone"
        error: str | None = None
        try:
            try:
                await super().__call__(scope, receive, send)
            except ExportAborted:
                # A user's action, not a server error: end without the last
                # body message, so the download fails (design decision 8).
                outcome, error = "failed", "ExportAborted"
            except ClientDisconnect:
                outcome = "client_gone"
            except BaseException as exc:
                outcome, error = "failed", type(exc).__name__
                raise
            else:
                outcome = "complete" if self.finished else "client_gone"
        finally:
            try:
                await self.body_iterator.aclose()  # type: ignore[attr-defined]
            finally:
                release(self.lease)
                logger.info(
                    "export ended user=%s format=%s thoughts=%d outcome=%s%s",
                    self.lease.user_id,
                    self.format,
                    self.thoughts,
                    outcome,
                    f" error={error}" if error else "",
                )
