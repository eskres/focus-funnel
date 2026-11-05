"""What the two tools do: parse their arguments, and turn a search into the
compact result the model reads and the sources the chat shows."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import SearchConfig
from app.chat.prompt import MAX_PARTS
from app.chat.refs import Refs, normal_ref
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.models import User
from app.provider_config import get_providers_config
from app.thoughts.categories import clean_name
from app.thoughts.dates import (
    DEFAULT_ZONE,
    local_day,
    parse_when,
    status_mark,
    thought_date_text,
    when_of,
)
from app.thoughts.search import SearchResult, search_thoughts

NO_MATCH = (
    "No filed thoughts match. Say so plainly, and do not answer as if the user had "
    "filed something."
)
NO_DATED_MATCH = (
    "No filed thoughts are dated in those days. Say so plainly, and do not answer as "
    "if the user had filed something."
)
NO_FILTERED_MATCH = (
    "No filed thoughts match those filters. Say so plainly, and do not answer as if "
    "the user had filed something."
)
# The statuses the search tool offers (thought-status design decision 12).
SEARCH_STATUSES = ("open",)
ALREADY_PROPOSED = (
    "Error: a proposal is already shown in this turn, and nothing was proposed now. "
    "Do not call propose_thought again in this turn: one proposal holds every "
    "thought as its parts. Now reply to the user's latest message."
)

PROPOSAL_SHOWN = (
    "The proposal is now shown to the user as a card they can edit and confirm. "
    "Nothing is saved until they confirm, so do not say it is saved, noted, added, "
    "or recorded, or that you will remember it: say it is ready for them to check "
    "and confirm. Do not call "
    "propose_thought again in this turn. Now reply to the user's latest message. "
    "If it held only what you proposed, reply in one short sentence."
)


class ToolArgumentError(ValueError):
    """The model called a tool with arguments that do not fit it."""


@dataclass(frozen=True)
class ProposalPart:
    title: str
    summary: str
    tags: list[str]
    category: str | None
    # The date, {start, end, time_zone}, or two choices of it, never both.
    when: dict[str, Any] | None = None
    when_choices: list[dict[str, Any]] | None = None
    # The ref of a seen thought to add to (thought-appending design decision 3),
    # and whether the model keeps the part new after a candidate round.
    add_to: str | None = None
    new: bool = False

    def as_dict(self) -> dict[str, Any]:
        """The part as stored on a proposal row, not yet saved. An addition's
        ref is kept as `add_to_ref`, which write_proposal() resolves."""
        stored: dict[str, Any] = {
            "title": self.title,
            "summary": self.summary,
            "tags": self.tags,
            "category": self.category,
            "when": self.when,
            "when_choices": self.when_choices,
            "thought_id": None,
        }
        if self.add_to is not None:
            stored["add_to_ref"] = self.add_to
        return stored


def _checked_date(value: Any, zone: ZoneInfo) -> dict[str, Any] | None:
    """A date from the model, with the turn's zone, or None when it fails the store's check."""
    if not isinstance(value, dict):
        return None
    try:
        # The model never names a zone: the server stamps the turn's.
        columns = parse_when(
            {"start": value.get("start"), "end": value.get("end"), "time_zone": zone.key}
        )
    except ApiError:
        return None
    return when_of(columns)


def _dates(item: dict[str, Any], zone: ZoneInfo) -> tuple[dict | None, list[dict] | None]:
    """A part's date or its two choices (thought-dates design decision 2).

    Choices win over a single date; a choice that fails the check is dropped;
    one choice left becomes the date; more than two keep the first two. A date
    that fails the check is dropped, and the rest of the part is kept.
    """
    choices = item.get("when_choices")
    if isinstance(choices, list) and choices:
        valid: list[dict[str, Any]] = []
        for choice in choices:
            checked = _checked_date(choice, zone)
            if checked is not None and checked not in valid:
                valid.append(checked)
        if not valid:
            return None, None
        if len(valid) == 1:
            return valid[0], None
        return None, valid[:2]
    return _checked_date(item.get("when"), zone), None


def _parse_part(
    item: Any, where: str, categories: list[str], zone: ZoneInfo
) -> ProposalPart:
    if not isinstance(item, dict):
        raise ToolArgumentError(f"{where} must be an object")
    title = item.get("title")
    summary = item.get("summary")
    tags = item.get("tags", [])
    category = item.get("category")
    if not isinstance(title, str) or not title.strip():
        raise ToolArgumentError(f"{where}title must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ToolArgumentError(f"{where}summary must be a non-empty string")
    if tags is None:
        tags = []
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ToolArgumentError(f"{where}tags must be a list of strings")
    cleaned_tags: list[str] = []
    for tag in tags:
        tag = tag.strip()
        if tag and tag not in cleaned_tags:
            cleaned_tags.append(tag)
    # A category the user does not have is dropped, so the card shows none.
    named = clean_name(category) if isinstance(category, str) else None
    when, when_choices = _dates(item, zone)
    return ProposalPart(
        title=title.strip(),
        summary=summary.strip(),
        tags=cleaned_tags,
        category=named if named in categories else None,
        when=when,
        when_choices=when_choices,
        add_to=_add_to(item.get("add_to"), where),
        new=item.get("new") is True or str(item.get("new")).lower() == "true",
    )


def _add_to(value: Any, where: str) -> str | None:
    """The ref a part adds to, written as the server writes refs. Text that
    is not a ref is kept as it is: it names no seen thought, so the part is
    filed as new."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ToolArgumentError(f"{where}add_to must be a ref such as T1")
    return normal_ref(value) or value.strip()


def parse_proposal(
    arguments: dict[str, Any], categories: list[str], zone: ZoneInfo | None = None
) -> list[ProposalPart]:
    """The parts of a propose_thought call, each date stamped with the turn's zone.

    The call's shape is {"thoughts": [...]}. A call with title, summary, and
    tags at the top, as the tool once took, is read as one part.
    """
    zone = zone or ZoneInfo(DEFAULT_ZONE)
    if "thoughts" not in arguments and "title" in arguments:
        return [_parse_part(arguments, "", categories, zone)]
    items = arguments.get("thoughts")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_PARTS:
        raise ToolArgumentError(f"thoughts must be a list of 1 to {MAX_PARTS} thoughts")
    parts = [
        _parse_part(item, f"thoughts[{index}].", categories, zone)
        for index, item in enumerate(items)
    ]
    # Two parts of one proposal never add to the same thought.
    named: set[str] = set()
    for part in parts:
        if part.add_to is None:
            continue
        if part.add_to in named:
            raise ToolArgumentError(
                f"two thoughts add to {part.add_to}; give each a different add_to, or put "
                "what they add into one thought"
            )
        named.add(part.add_to)
    return parts


@dataclass(frozen=True)
class SearchArguments:
    # None when the search lists the thoughts that pass its filters.
    query: str | None
    tags: list[str] | None = None
    since: date | None = None
    # The days the thought itself is dated on, not the day it was filed.
    dated_from: date | None = None
    dated_to: date | None = None
    # Only thoughts with this status (`open`) or this category, as stored.
    status: str | None = None
    category: str | None = None

    @property
    def dated(self) -> bool:
        return self.dated_from is not None or self.dated_to is not None

    @property
    def by_date_only(self) -> bool:
        """No query and a filter on the thought's days: a list in date order."""
        return self.query is None and self.dated

    @property
    def listed(self) -> bool:
        """No query: a list of the thoughts that pass the filters."""
        return self.query is None

    @property
    def summary(self) -> str:
        """The tool's line in the chat (thought-status design decision 12)."""
        if self.query is not None:
            return f"Searched your thoughts for “{self.query}”"
        status = f" {self.status}" if self.status else ""
        category = f" in {self.category}" if self.category else ""
        return f"Listed your{status} thoughts{category}"

    @property
    def days_text(self) -> str:
        """The thought's days searched, for the tool's line in the chat."""
        if self.dated_from and self.dated_to:
            if self.dated_from == self.dated_to:
                return f"on {self.dated_from.isoformat()}"
            return f"{self.dated_from.isoformat()} to {self.dated_to.isoformat()}"
        if self.dated_from:
            return f"from {self.dated_from.isoformat()}"
        if self.dated_to:
            return f"up to {self.dated_to.isoformat()}"
        return ""


# date.fromisoformat also takes "20261002" and "2026-W40-5".
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _day(arguments: dict[str, Any], name: str) -> date | None:
    value = arguments.get(name)
    if value is None:
        return None
    if isinstance(value, str) and _DAY.fullmatch(value.strip()):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ToolArgumentError(f"{name} must be a date written YYYY-MM-DD")


def parse_search(arguments: dict[str, Any]) -> SearchArguments:
    """The search call's arguments. A query is needed unless dated_from,
    dated_to, status, or category is given. The only status the tool offers
    is `open`; the category is cleaned as it is stored."""
    query = arguments.get("query")
    if query is not None and not isinstance(query, str):
        raise ToolArgumentError("query must be a string")
    query = query.strip() if query else ""
    tags = arguments.get("tags")
    if tags is not None and (
        not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)
    ):
        raise ToolArgumentError("tags must be a list of strings")
    since = arguments.get("since")
    if since is not None:
        try:
            since = date.fromisoformat(since) if isinstance(since, str) else None
        except ValueError:
            since = None
        if since is None:
            raise ToolArgumentError("since must be a date written YYYY-MM-DD")
    dated_from = _day(arguments, "dated_from")
    dated_to = _day(arguments, "dated_to")
    status = arguments.get("status")
    if status is not None and status not in SEARCH_STATUSES:
        raise ToolArgumentError("status must be open, or left out to find done thoughts too")
    category = arguments.get("category")
    if category is not None and not isinstance(category, str):
        raise ToolArgumentError("category must be a string")
    category = clean_name(category) if category else None
    if not query and dated_from is None and dated_to is None and not status and not category:
        raise ToolArgumentError(
            "query must be a non-empty string, unless dated_from, dated_to, status, "
            "or category is given"
        )
    if dated_from is not None and dated_to is not None and dated_to < dated_from:
        raise ToolArgumentError("dated_to must not be before dated_from")
    return SearchArguments(
        query=query or None,
        tags=tags or None,
        since=since,
        dated_from=dated_from,
        dated_to=dated_to,
        status=status,
        category=category or None,
    )


@dataclass
class SearchToolResult:
    text: str
    # The thoughts shown, in order, for the chat to list as sources:
    # {id, title, created_at, tags}. The model never sees the ids.
    sources: list[dict[str, Any]] = field(default_factory=list)


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def words_only_note(error: ApiError, provider_id: str) -> str:
    if error.code == ErrorCode.PROVIDER_KEY_MISSING:
        provider = get_providers_config().get(provider_id)
        label = provider.label if provider else provider_id
        return (
            f"Searched by words only: add your {label} API key in settings to also "
            "search by meaning. Tell the user."
        )
    if error.code in (ErrorCode.MODEL_UNAVAILABLE, ErrorCode.EMBEDDING_MISMATCH):
        return (
            "Searched by words only: the search index was built with an embedding model "
            "that no longer works here, and the operator needs to rebuild it. Tell the user."
        )
    return f"Searched by words only: {error.message} Tell the user."


def format_search_result(
    result: SearchResult,
    config: SearchConfig,
    settings: Settings,
    *,
    newest_first: bool = False,
    by_date: bool = False,
    filtered: bool = False,
    zone: ZoneInfo | None = None,
    refs: Refs | None = None,
) -> SearchToolResult:
    """The search result in as few tokens as the model can answer from.

    No ids (the model does not need them), summaries cut at summary_chars, an
    excerpt only for a raw-text match, and entries added best first until the
    next would pass budget_chars. Each entry gives the day it was filed and,
    for a dated thought, its date. `by_date` is a search by the thought's days
    with no query: its entries are in date order (thought-dates design
    decision 4). `filtered` is a search with a status or category filter: its
    no-match text names those filters. A thought whose status is not `open`
    gets ` · <status> <day>` after its filed day (thought-status design
    decision 12). The filed day is the user's local day in `zone` (UTC when not
    given), the same days as the model's today and its `since`. With the
    conversation's `refs`, each entry carries its thought's ref, and a thought
    shown for the first time is numbered after every other (thought-appending
    design decision 2).
    """
    filed_zone = zone or ZoneInfo(DEFAULT_ZONE)
    provider_id = result.embedding_provider or settings.embedding_provider
    note = [words_only_note(result.words_only, provider_id)] if result.words_only else []
    if not result.hits:
        nothing = NO_FILTERED_MATCH if filtered else NO_DATED_MATCH if by_date else NO_MATCH
        return SearchToolResult(text="\n".join([nothing, *note]))
    entries: list[str] = []
    sources: list[dict[str, Any]] = []
    used = 0
    for number, hit in enumerate(result.hits, start=1):
        thought = hit.thought
        ref = f"{refs.label(thought.id)} · " if refs is not None else ""
        heading = (
            f"{number}. {ref}{thought.title} · filed "
            f"{local_day(thought.created_at, filed_zone).isoformat()}"
            f"{status_mark(thought.status, thought.status_changed_at, filed_zone)}"
        )
        dated = thought_date_text(thought)
        if dated:
            heading += f" · on {dated}"
        if thought.tags:
            heading += " · " + " ".join(f"#{tag}" for tag in thought.tags)
        lines = [heading, "   " + _shorten(thought.summary, config.summary_chars)]
        if hit.excerpt:
            lines.append(f'   > "{hit.excerpt}"')
        entry = "\n".join(lines)
        if entries and used + len(entry) + 1 > config.budget_chars:
            break
        entries.append(entry)
        if refs is not None:
            refs.add(thought.id)
        sources.append(
            {
                "id": str(thought.id),
                "title": thought.title,
                "created_at": thought.created_at.isoformat(),
                "tags": list(thought.tags or []),
            }
        )
        used += len(entry) + 1
    shown = len(entries)
    more = max(result.total - shown, 0)
    if by_date:
        header = f"{shown} of your thoughts are dated in those days (date order):"
        footer = (
            [f"{more} more are dated in those days. Narrow the days or add tags to see them."]
            if more
            else []
        )
    else:
        order = "newest first" if newest_first else "best first"
        header = f"{shown} of your thoughts match ({order}):"
        footer = (
            [f"{more} more matched. Add tags or a start date to narrow the search."]
            if more
            else []
        )
    return SearchToolResult(text="\n".join([header, *entries, *footer, *note]), sources=sources)


async def search_tool_result(
    session: AsyncSession,
    user: User,
    arguments: SearchArguments,
    *,
    settings: Settings,
    config: SearchConfig,
    conversation_id: uuid.UUID | None = None,
    http_client: httpx2.AsyncClient | None = None,
    zone: ZoneInfo | None = None,
    refs: Refs | None = None,
) -> SearchToolResult:
    """The search tool's result for the model, with each thought's ref when
    the conversation's `refs` are given. A failed search becomes a note, never an error.

    The dates are the user's local days in `zone` (UTC when not given)."""
    result = await search_thoughts(
        session,
        user,
        arguments.query,
        settings=settings,
        tags=arguments.tags,
        since=arguments.since,
        dated_from=arguments.dated_from,
        dated_to=arguments.dated_to,
        status=arguments.status,
        category=arguments.category,
        zone=zone,
        conversation_id=conversation_id,
        http_client=http_client,
        config=config,
    )
    return format_search_result(
        result,
        config,
        settings,
        # A list with no query and no date filter is newest filed first.
        newest_first=arguments.listed and not arguments.dated,
        by_date=arguments.by_date_only,
        filtered=arguments.status is not None or arguments.category is not None,
        zone=zone,
        refs=refs,
    )
