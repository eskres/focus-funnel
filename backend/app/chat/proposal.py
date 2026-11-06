"""Proposals: writing them with their raw text, and offering the held one.

Each propose_thought call writes one proposals row. Its raw text is fixed
there, from the user's own messages, never from the browser. The held
proposal is the latest with a part not yet saved; the app offers it before
archive and /compact. When none is held and the user said something since
the last saved proposal, the model is asked for one, and may decline.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ChatConfig
from app.chat.conversations import list_messages, use_model
from app.chat.loadout import get_default_model, temperature_for
from app.chat.model_call import ModelCall, open_model_call
from app.chat.prompt import (
    PROPOSE_TOOL,
    build_context,
    offer_note,
    text_for_model,
    tool_arguments,
    tools_for,
    unsaved_parts,
)
from app.chat.refs import (
    Refs,
    SeenThought,
    conversation_refs,
    date_fields,
    normal_ref,
    resolve_additions,
    saved_ids,
    status_fields,
)
from app.chat.similar import Check, candidates_note, check_parts, with_similar
from app.chat.tools import ProposalPart, ToolArgumentError, ToolRefusal, parse_proposal
from app.chat.usage import cap_state, completion_usage, record_usage
from app.config import Settings
from app.errors import model_not_set
from app.models import Conversation, Message, Proposal, Thought, User
from app.providers import provider_for_user
from app.thoughts.additions import proposal_additions
from app.thoughts.categories import user_categories
from app.thoughts.dates import DEFAULT_ZONE, today_in
from app.thoughts.store import MAX_RAW_TEXT, known_tags

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Filing:
    """What the proposal tool offers one user: their categories and known tags."""

    categories: list[str]
    known_tags: list[str]

    @property
    def tools(self) -> list[dict[str, Any]]:
        return tools_for(self.categories, self.known_tags)

    @property
    def offer_tools(self) -> list[dict[str, Any]]:
        """The tools of the offer's asked calls: no marks (thought-status design
        decision 6)."""
        return tools_for(self.categories, self.known_tags, marks=False)


async def filing_for(session: AsyncSession, user: User, config: ChatConfig) -> Filing:
    return Filing(
        categories=await user_categories(session, user),
        known_tags=await known_tags(session, user, config.filing.known_tags),
    )


async def held_proposal(session: AsyncSession, conversation: Conversation) -> Proposal | None:
    if conversation.held_proposal_id is None:
        return None
    return await session.get(Proposal, conversation.held_proposal_id)


def held_parts(proposal: Proposal | None) -> list[dict[str, Any]] | None:
    """The parts the held-proposal note lists, or None when nothing is held."""
    if proposal is None or not unsaved_parts(proposal.parts):
        return None
    return proposal.parts


async def list_proposals(session: AsyncSession, conversation: Conversation) -> list[Proposal]:
    rows = await session.execute(
        select(Proposal)
        .where(Proposal.conversation_id == conversation.id)
        .order_by(Proposal.position, Proposal.created_at)
    )
    return list(rows.scalars())


@dataclass(frozen=True)
class RawText:
    text: str
    from_position: int
    to_position: int


def fit_raw_text(messages: list[Message]) -> RawText:
    """The user messages as one text, keeping the most recent whole messages
    that fit the thought store's limit. A latest message longer than the limit
    alone is cut at its end."""
    texts = [(message.position, text_for_model(message.content or "")) for message in messages]
    last_position, last_text = texts[-1]
    if len(last_text) > MAX_RAW_TEXT:
        return RawText(last_text[:MAX_RAW_TEXT], last_position, last_position)
    kept: list[tuple[int, str]] = []
    length = 0
    for position, text in reversed(texts):
        added = len(text) + (2 if kept else 0)
        if length + added > MAX_RAW_TEXT:
            break
        kept.insert(0, (position, text))
        length += added
    return RawText("\n\n".join(text for _, text in kept), kept[0][0], last_position)


def filed_part(part: dict[str, Any]) -> bool:
    """A part that filed a thought or added to one: saved, and not a mark,
    which files nothing (thought-status design decision 8)."""
    return bool(part.get("thought_id")) and not part.get("mark")


def discussion_start(proposals: list[Proposal]) -> int:
    """The position after the latest proposal with a part that filed or
    added to a thought, or 0. A confirmed mark does not count."""
    for proposal in reversed(proposals):
        if any(filed_part(part) for part in proposal.parts):
            return proposal.to_position + 1
    return 0


async def refs_for(
    session: AsyncSession,
    conversation: Conversation,
    messages: list[Message] | None = None,
    *,
    before_next_row: bool = False,
) -> Refs:
    """The conversation's refs as its rows stand now (design decision 2).

    A running turn passes `before_next_row` for refs it numbers new thoughts
    from and stores in its next row. A card confirmed while the turn runs is
    stamped at that row's position, and counts after the row's thoughts
    there, so it is left out now and numbered after them, as every later
    load numbers it: a number the model is shown never moves.
    """
    if messages is None:
        messages = await list_messages(session, conversation)
    proposals = await list_proposals(session, conversation)
    seen_before = None
    if before_next_row:
        seen_before = messages[-1].position + 1 if messages else 0
    return await conversation_refs(
        session, conversation.user_id, messages, proposals, seen_before=seen_before
    )


async def raw_text_for(
    session: AsyncSession, conversation: Conversation, messages: list[Message], *, push: bool
) -> RawText:
    """The raw text of a proposal made now (design decision 3).

    For /push, the turn's message. Otherwise the user's messages since the
    latest proposal with a saved part, or since the start. Compacted messages
    count; summaries are not user messages.
    """
    users = [message for message in messages if message.role == "user"]
    if push:
        return fit_raw_text(users[-1:])
    start = discussion_start(await list_proposals(session, conversation))
    discussion = [message for message in users if message.position >= start] or users[-1:]
    return fit_raw_text(discussion)


UNSEEN_MARK = (
    "Error: {ref} is not a thought this conversation has seen. Search for it with "
    "status open, then call propose_thought with the ref the search gives."
)
GONE_MARK = (
    "Error: {ref} no longer exists. Do not propose marking it done; tell the user it "
    "was deleted."
)
NOT_OPEN_MARK = (
    "Error: {ref} is already {status}. Do not propose marking it done; tell the user it "
    "is already {status}."
)


def _ref_list(refs: list[str]) -> str:
    return refs[0] if len(refs) == 1 else ", ".join(refs[:-1]) + " and " + refs[-1]


def mark_ids(refs: Refs, marks: Sequence[str]) -> dict[str, uuid.UUID | None]:
    """The thought id each mark's ref names, or None for a ref this
    conversation has not seen (text that is not a ref, or a number past the
    refs). A deleted thought keeps its number, so its id is still known."""
    ids: dict[str, uuid.UUID | None] = {}
    for ref in marks:
        normal = normal_ref(ref)
        number = int(normal[1:]) if normal else 0
        ids[ref] = refs.numbered[number - 1] if 1 <= number <= len(refs.numbered) else None
    return ids


def mark_refusal(
    marks: Sequence[str],
    ids: dict[str, uuid.UUID | None],
    statuses: dict[uuid.UUID, str],
    others: int,
) -> str | None:
    """The tool result for a call's marks, or None when every mark can apply
    (thought-status design decision 6). `statuses` holds the status of each
    of the user's thoughts that exists. One line per mark that cannot apply,
    in the order of the call, then, when the call had `others` (entries in
    thoughts) or a mark that passed, the closing line naming every refused
    ref."""
    lines: list[str] = []
    refused: list[str] = []
    unseen = False
    for ref in marks:
        thought_id = ids[ref]
        if thought_id is None:
            lines.append(UNSEEN_MARK.format(ref=ref))
            unseen = True
        elif thought_id not in statuses:
            lines.append(GONE_MARK.format(ref=ref))
        elif statuses[thought_id] != "open":
            lines.append(NOT_OPEN_MARK.format(ref=ref, status=statuses[thought_id]))
        else:
            continue
        refused.append(ref)
    if not refused:
        return None
    if others or len(refused) < len(marks):
        closing = (
            "Nothing was proposed. Call propose_thought again with the call's other "
            f"parts, without {_ref_list(refused)}"
        )
        closing += ", and with the ref the search gives, in one call." if unseen else "."
        lines.append(closing)
    return "\n".join(lines)


async def resolve_marks(
    session: AsyncSession,
    user_id: uuid.UUID,
    refs: Refs,
    marks: Sequence[str],
    others: int,
) -> list[dict[str, Any]]:
    """The marks of a call as stored, in order, or a ToolRefusal (thought-status
    design decisions 5 and 6).

    One query reads every mark's thought, filtered by its owner, so another
    user's thought reads as gone before its status is looked at. A ref this
    conversation has not seen, a thought that is gone, and one whose status
    is not open each get one line (mark_refusal()). A stored mark has the
    thought's title and category now, for the card only.
    """
    if not marks:
        return []
    ids = mark_ids(refs, marks)
    known = [thought_id for thought_id in ids.values() if thought_id is not None]
    statuses: dict[uuid.UUID, str] = {}
    if known:
        rows = await session.execute(
            select(Thought.id, Thought.status).where(
                Thought.id.in_(known), Thought.user_id == user_id
            )
        )
        statuses = {row.id: row.status for row in rows}
    refusal = mark_refusal(marks, ids, statuses, others)
    if refusal is not None:
        raise ToolRefusal(refusal)
    resolved: list[dict[str, Any]] = []
    for ref in marks:
        thought_id = ids[ref]
        seen = refs.thoughts.get(thought_id)
        resolved.append(
            {
                "mark": str(thought_id),
                "title": seen.title if seen is not None else "",
                "summary": "",
                "tags": [],
                "category": seen.category if seen is not None else None,
                "thought_id": None,
            }
        )
    return resolved


async def write_proposal(
    session: AsyncSession,
    conversation: Conversation,
    parts: list[dict[str, Any]],
    position: int,
    *,
    push: bool = False,
    refs: Refs | None = None,
) -> tuple[Proposal, uuid.UUID | None]:
    """Write a proposal and hold it. Returns it, and the id of the held
    proposal it replaced, if any. A part's ref is resolved now, into an
    addition to a seen thought or a new thought (design decision 3), from
    `refs` when the caller has them. A part's `mark_ref` is resolved into a
    stored mark, or the call is refused with a ToolRefusal and nothing is
    written (thought-status design decision 6). Marks come after the other
    parts. A proposal whose parts are all marks is not held and replaces no
    held proposal (thought-status design decision 9). The caller commits."""
    messages = await list_messages(session, conversation)
    if any(
        part.get("add_to_ref") is not None or part.get("mark_ref") is not None for part in parts
    ):
        if refs is None:
            refs = await refs_for(session, conversation, messages)
        if any(part.get("mark_ref") is not None for part in parts):
            marks = await resolve_marks(
                session,
                conversation.user_id,
                refs,
                [part["mark_ref"] for part in parts if part.get("mark_ref") is not None],
                sum(1 for part in parts if part.get("mark_ref") is None and not part.get("mark")),
            )
            resolved = iter(marks)
            parts = [next(resolved) if part.get("mark_ref") is not None else part for part in parts]
        parts = resolve_additions(parts, refs)
    parts = [part for part in parts if not part.get("mark")] + [
        part for part in parts if part.get("mark")
    ]
    raw = await raw_text_for(session, conversation, messages, push=push)
    proposal = Proposal(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        position=position,
        from_position=raw.from_position,
        to_position=raw.to_position,
        raw_text=raw.text,
        parts=parts,
    )
    held = await held_proposal(session, conversation)
    session.add(proposal)
    # The conversation points at the row, so the row goes in first.
    await session.flush()
    replaced = None
    if unsaved_parts(parts):
        if held_parts(held) is not None:
            # The card of the proposal it replaces shows as replaced, and can still be confirmed.
            held.replaced_by_id = proposal.id
            replaced = held.id
        conversation.held_proposal_id = proposal.id
    return proposal, replaced


@dataclass(frozen=True)
class PartLookup:
    """What a proposal's payload reads beside its stored parts: the user's
    thoughts its parts name, as they are now, by id as text (a deleted or
    foreign one has no entry), and whether each addition made from it is
    undone, by (proposal id, thought id) as text."""

    thoughts: dict[str, SeenThought]
    additions: dict[tuple[str, str], bool]


def _named_ids(proposals: list[Proposal]) -> list[uuid.UUID]:
    """Every thought id these proposals' parts name: saved, added to, marked, or similar."""
    ids: set[uuid.UUID] = set()
    for proposal in proposals:
        for part in proposal.parts:
            similar = part.get("similar")
            for value in (
                part.get("thought_id"),
                part.get("add_to"),
                part.get("mark"),
                similar.get("thought_id") if isinstance(similar, dict) else None,
            ):
                if value:
                    ids.add(uuid.UUID(str(value)))
    return sorted(ids)


async def _additions_of(
    session: AsyncSession, user: User, proposals: list[Proposal]
) -> dict[tuple[str, str], bool]:
    """The additions made from these proposals; no query when no part is saved."""
    saved = [p.id for p in proposals if any(part.get("thought_id") for part in p.parts)]
    return await proposal_additions(session, user, saved)


async def part_lookup(session: AsyncSession, user: User, proposals: list[Proposal]) -> PartLookup:
    """The lookup for these proposals' payloads: one query for every thought
    their parts name, and one for their additions, however many parts and
    additions there are (design decisions 3 and 9)."""
    ids = _named_ids(proposals)
    thoughts: dict[str, SeenThought] = {}
    if ids:
        rows = await session.execute(
            select(Thought).where(Thought.id.in_(ids), Thought.user_id == user.id)
        )
        for thought in rows.scalars():
            thoughts[str(thought.id)] = SeenThought(
                ref="",
                id=thought.id,
                title=thought.title,
                summary=thought.summary,
                tags=list(thought.tags or []),
                category=thought.category,
                created_at=thought.created_at,
                updated_at=thought.updated_at,
                **date_fields(thought),
                **status_fields(thought),
            )
    return PartLookup(thoughts, await _additions_of(session, user, proposals))


async def lookup_from_refs(
    session: AsyncSession, user: User, refs: Refs, proposals: list[Proposal]
) -> PartLookup:
    """The lookup for a conversation whose refs are loaded: the refs already
    hold every thought its parts name, so only the additions are read."""
    thoughts = {str(thought_id): thought for thought_id, thought in refs.thoughts.items()}
    return PartLookup(thoughts, await _additions_of(session, user, proposals))


def _thought_fields(thought: SeenThought) -> dict[str, Any]:
    return {
        "title": thought.title,
        "summary": thought.summary,
        "tags": list(thought.tags),
        "category": thought.category,
        "created_at": thought.created_at.isoformat(),
        # The version a confirm sends back as based_on, unchanged.
        "updated_at": thought.updated_at.isoformat(),
    }


def proposal_payload(proposal: Proposal, lookup: PartLookup | None = None) -> dict[str, Any]:
    """A proposal as the chat receives it, in the event and in the conversation.

    From `lookup`, each part also carries its thought's current title
    (`saved_title`) and whether that thought was deleted (`deleted`); for an
    addition or a mark, `target`, the thought it adds to or marks as it is
    now, or `{"deleted": true}`; for a new idea with a strong match, `similar`, that
    match as it is now, or null once it is gone; and once saved as an
    addition, `added`, and `undone` once that addition was undone. Without a
    lookup a part has none of these.
    """
    thoughts = lookup.thoughts if lookup is not None else None
    additions = lookup.additions if lookup is not None else {}

    def with_saved(part: dict[str, Any]) -> dict[str, Any]:
        thought_id = part.get("thought_id")
        known = thoughts is not None and thought_id is not None
        saved = thoughts.get(str(thought_id)) if known else None
        add_to = part.get("add_to")
        mark = part.get("mark")
        target = None
        if thoughts is not None and (add_to or mark):
            current = thoughts.get(str(add_to or mark))
            target = _thought_fields(current) if current else {"deleted": True}
        similar = part.get("similar")
        match = None
        if thoughts is not None and isinstance(similar, dict) and similar.get("thought_id"):
            current = thoughts.get(str(similar["thought_id"]))
            if current is not None:
                match = {"thought_id": str(current.id), **_thought_fields(current)}
        addition = additions.get((str(proposal.id), str(thought_id))) if thought_id else None
        return {
            # Where the part was confirmed only fixes its ref; the chat does not need it.
            **{key: value for key, value in part.items() if key != "seen_position"},
            "saved_title": saved.title if saved is not None else None,
            "deleted": known and saved is None,
            # An addition's thought and version, null for a new thought.
            "add_to": add_to,
            "based_on": part.get("based_on"),
            # A status part: the thought it marks done (thought-status decision 10).
            "mark": mark,
            "target": target,
            "similar": match,
            "added": addition is not None,
            "undone": bool(addition),
        }

    return {
        "id": str(proposal.id),
        "position": proposal.position,
        "parts": [with_saved(part) for part in proposal.parts],
        "replaced_by": str(proposal.replaced_by_id) if proposal.replaced_by_id else None,
    }


async def asked_proposal(
    session: AsyncSession,
    call: ModelCall,
    context: list[dict[str, Any]],
    filing: Filing,
    conversation_id: uuid.UUID | None = None,
    zone: ZoneInfo | None = None,
) -> list[ProposalPart] | None:
    """Ask the model for a proposal, which it may decline. Returns its parts,
    or None when it calls no tool or its arguments do not make a proposal.

    Not forced: a forced call makes the model propose something even when
    only small talk is left. The tool takes no marks, and any mark the model
    sends is ignored unchecked (thought-status design decision 6)."""
    completion = await call.complete(context, tools=filing.offer_tools)
    await record_usage(session, call, "proposal", *completion_usage(completion), conversation_id)
    choices = completion.choices or []
    tool_calls = (choices[0].message.tool_calls if choices else None) or []
    for tool_call in tool_calls:
        if tool_call.function.name != PROPOSE_TOOL:
            continue
        try:
            parts = parse_proposal(
                tool_arguments(tool_call.function.arguments),
                filing.categories,
                zone,
                offered=True,
            )
        except (ValueError, ToolArgumentError):
            logger.info("The offered proposal call returned arguments that do not fit")
            continue
        return parts or None
    return None


async def offer_proposal(
    session: AsyncSession,
    user: User,
    conversation: Conversation,
    config: ChatConfig,
    settings: Settings,
    http_client: httpx2.AsyncClient | None = None,
    zone: ZoneInfo | None = None,
) -> Proposal | None:
    """The proposal to show before archive or /compact, held from now on.

    Returns the held proposal without a model call when it has a part not
    yet saved, and None when the conversation has no discussion to propose.
    The model is told the user's local date in `zone` (UTC when not given),
    and the proposal's dates are stamped with it.
    """
    zone = zone or ZoneInfo(DEFAULT_ZONE)
    held = await held_proposal(session, conversation)
    if held_parts(held) is not None:
        return held
    messages = await list_messages(session, conversation)
    proposals = await list_proposals(session, conversation)
    # Nothing said since the last saved proposal: nothing new to file.
    start = discussion_start(proposals)
    if not any(m.role == "user" and not m.compacted and m.position >= start for m in messages):
        return None
    # At the spend cap no model is asked, and the action goes ahead with no
    # offer (stop-and-spend-cap design decision 9).
    cap = await cap_state(session, user.id)
    if cap is not None and cap.reached:
        return None

    if conversation.model is None:
        default = await get_default_model(session, user)
        if default is None:
            raise model_not_set()
        use_model(conversation, default)
    filing = await filing_for(session, user, config)
    provider = await provider_for_user(session, user, conversation.provider_id, settings)
    call = await open_model_call(
        session,
        user,
        provider,
        conversation.model,
        temperature=await temperature_for(session, user, config),
        max_tokens=config.reply_max_tokens,
        reasoning_effort=conversation.reasoning_effort,
        settings=settings,
        http_client=http_client,
    )
    refs = await conversation_refs(session, user.id, messages, proposals)
    # Every thought the conversation filed is listed, past the cap, so the
    # model can add to it rather than file it again.
    seen_note = refs.note(config.filing, keep=saved_ids(proposals), zone=zone)

    async def check(parts: list[ProposalPart], again: bool) -> Check:
        return await check_parts(
            session,
            user,
            parts,
            refs,
            config=config,
            settings=settings,
            again=again,
            conversation_id=conversation.id,
            http_client=http_client,
        )

    try:
        context = build_context(
            messages, today=today_in(zone), seen_note=seen_note, refs=refs.by_id()
        )
        context.append({"role": "system", "content": offer_note(seen_note is not None)})
        parts = await asked_proposal(session, call, context, filing, conversation.id, zone)
        if parts is None:
            return None
        checked = await check(parts, again=False)
        if checked.has_candidates:
            # Layer 2 (design decision 4): the model is asked once more, with
            # the candidates, numbered after the conversation's refs. It may
            # decline again, and then nothing is offered.
            note, _ = candidates_note(
                parts, checked, refs, config.filing.seen_summary_chars, zone
            )
            context.append({"role": "system", "content": note})
            parts = await asked_proposal(
                session, call, context, filing, conversation.id, zone
            )
            if parts is None:
                return None
            checked = await check(parts, again=True)
    finally:
        await call.aclose()
    stored = with_similar([part.as_dict() for part in parts], checked)
    proposal, _ = await write_proposal(
        session, conversation, stored, messages[-1].position, refs=refs
    )
    await session.commit()
    return proposal
