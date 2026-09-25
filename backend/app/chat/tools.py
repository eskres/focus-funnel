"""What the two tools do: parse their arguments, and turn a search into the
compact result the model reads and the sources the chat shows."""

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import SearchConfig
from app.chat.prompt import MAX_PARTS
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.models import User
from app.provider_config import get_providers_config
from app.thoughts.categories import clean_name
from app.thoughts.search import SearchResult, search_thoughts

NO_MATCH = (
    "No filed thoughts match. Say so plainly, and do not answer as if the user had "
    "filed something."
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

    def as_dict(self) -> dict[str, Any]:
        """The part as stored on a proposal row, not yet saved."""
        return {
            "title": self.title,
            "summary": self.summary,
            "tags": self.tags,
            "category": self.category,
            "thought_id": None,
        }


def _parse_part(item: Any, where: str, categories: list[str]) -> ProposalPart:
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
    return ProposalPart(
        title=title.strip(),
        summary=summary.strip(),
        tags=cleaned_tags,
        category=named if named in categories else None,
    )


def parse_proposal(arguments: dict[str, Any], categories: list[str]) -> list[ProposalPart]:
    """The parts of a propose_thought call.

    The call's shape is {"thoughts": [...]}. A call with title, summary, and
    tags at the top, as the tool once took, is read as one part.
    """
    if "thoughts" not in arguments and "title" in arguments:
        return [_parse_part(arguments, "", categories)]
    items = arguments.get("thoughts")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_PARTS:
        raise ToolArgumentError(f"thoughts must be a list of 1 to {MAX_PARTS} thoughts")
    return [
        _parse_part(item, f"thoughts[{index}].", categories) for index, item in enumerate(items)
    ]


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
    sources: list[dict[str, Any]] = []
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
    header = f"{shown} of your thoughts match ({order}):"
    more = max(result.total - shown, 0)
    footer = (
        [f"{more} more matched. Add tags or a start date to narrow the search."] if more else []
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
