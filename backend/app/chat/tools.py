"""What the two tools do. Each sits behind one function, so the changes that
add thought storage and search replace it without touching the tool loop."""

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import SearchConfig
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.models import User
from app.provider_config import get_providers_config
from app.thoughts.search import SearchResult, search_thoughts

NO_MATCH = "No filed thoughts match."
PROPOSAL_SHOWN = (
    "The proposal is now shown to the user as a card they can edit and confirm. "
    "Nothing is saved until they confirm. Do not call propose_thought again in this "
    "turn. Now reply to the user's latest message. If it held only what you "
    "proposed, reply in one short sentence."
)


class ToolArgumentError(ValueError):
    """The model called a tool with arguments that do not fit it."""


@dataclass(frozen=True)
class Proposal:
    title: str
    summary: str
    tags: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "summary": self.summary, "tags": self.tags}


def parse_proposal(arguments: dict[str, Any]) -> Proposal:
    title = arguments.get("title")
    summary = arguments.get("summary")
    tags = arguments.get("tags", [])
    if not isinstance(title, str) or not title.strip():
        raise ToolArgumentError("title must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ToolArgumentError("summary must be a non-empty string")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ToolArgumentError("tags must be a list of strings")
    return Proposal(
        title=title.strip(),
        summary=summary.strip(),
        tags=[tag.strip() for tag in tags if tag.strip()],
    )


@dataclass(frozen=True)
class SearchArguments:
    query: str
    tags: list[str] | None = None
    since: date | None = None


def parse_search(arguments: dict[str, Any]) -> SearchArguments:
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolArgumentError("query must be a non-empty string")
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
    return SearchArguments(query=query.strip(), tags=tags or None, since=since)


@dataclass
class SearchToolResult:
    text: str
    # The ids of the thoughts shown, for the chat to list as sources.
    thought_ids: list[str] = field(default_factory=list)


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
    result: SearchResult, config: SearchConfig, settings: Settings, *, newest_first: bool = False
) -> SearchToolResult:
    """The search result in as few tokens as the model can answer from.

    No ids (the model does not need them), summaries cut at summary_chars, an
    excerpt only for a raw-text match, and entries added best first until the
    next would pass budget_chars.
    """
    provider_id = result.embedding_provider or settings.embedding_provider
    note = [words_only_note(result.words_only, provider_id)] if result.words_only else []
    if not result.hits:
        return SearchToolResult(text="\n".join([NO_MATCH, *note]))
    order = "newest first" if newest_first else "best first"
    entries: list[str] = []
    ids: list[str] = []
    used = 0
    for number, hit in enumerate(result.hits, start=1):
        thought = hit.thought
        heading = f"{number}. {thought.title} · {thought.created_at.date().isoformat()}"
        if thought.tags:
            heading += " · " + " ".join(f"#{tag}" for tag in thought.tags)
        lines = [heading, "   " + _shorten(thought.summary, config.summary_chars)]
        if hit.excerpt:
            lines.append(f'   > "{hit.excerpt}"')
        entry = "\n".join(lines)
        if entries and used + len(entry) + 1 > config.budget_chars:
            break
        entries.append(entry)
        ids.append(str(thought.id))
        used += len(entry) + 1
    shown = len(entries)
    header = f"{shown} of your thoughts match ({order}):"
    more = max(result.total - shown, 0)
    footer = (
        [f"{more} more matched. Add tags or a start date to narrow the search."] if more else []
    )
    return SearchToolResult(text="\n".join([header, *entries, *footer, *note]), thought_ids=ids)


async def search_tool_result(
    session: AsyncSession,
    user: User,
    arguments: SearchArguments,
    *,
    settings: Settings,
    config: SearchConfig,
    conversation_id: uuid.UUID | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> SearchToolResult:
    """The search tool's result for the model. A failed search becomes a note, never an error."""
    result = await search_thoughts(
        session,
        user,
        arguments.query,
        settings=settings,
        tags=arguments.tags,
        since=arguments.since,
        conversation_id=conversation_id,
        http_client=http_client,
        config=config,
    )
    return format_search_result(result, config, settings)


@dataclass(frozen=True)
class SaveOutcome:
    saved: bool
    message: str


async def save_thought(user: User, proposal: Proposal) -> SaveOutcome:
    """Hand a confirmed proposal to thought storage. Replaced by push-and-pull."""
    return SaveOutcome(
        saved=False, message="Saving thoughts is not available yet. Copy the text to keep it."
    )
