"""One chat turn: stream the model's answer, run its tools, and store it all.

The first model call is opened before the response starts, so its failures
are ordinary error responses. Everything after that arrives as events.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.actions import ACTION_SHOWN, ActionTarget, action_payload, new_action
from app.chat.config import ChatConfig
from app.chat.context import compact_suggestion
from app.chat.conversations import ends_answered, interrupted_answer, last_message, next_position
from app.chat.model_call import ModelCall
from app.chat.prompt import (
    PROPOSE_TOOL,
    SEARCH_TOOL,
    drop_held_note,
    forced_tool,
    tool_arguments,
)
from app.chat.proposal import Filing, part_lookup, proposal_payload, refs_for, write_proposal
from app.chat.similar import candidates_note, check_parts, with_similar
from app.chat.sse import Event
from app.chat.tool_providers import (
    ToolOutcome,
    ToolProvider,
    TurnToolState,
    holds_connector_data,
    tool_label,
)
from app.chat.usage import record_usage, usage_warning
from app.chat.tools import (
    ALREADY_PROPOSED,
    PROPOSAL_SHOWN,
    ToolArgumentError,
    parse_proposal,
    parse_search,
    search_tool_result,
)
from app.config import Settings, get_settings
from app.errors import ApiError, ErrorCode, output_limit_reached, tool_loop_limit
from app.models import Conversation, Message, UsageEvent, User
from app.ownership import not_found
from app.provider_config import StreamUsage
from app.thoughts.dates import DEFAULT_ZONE

logger = logging.getLogger(__name__)


@dataclass
class RoundState:
    """What one streamed model call produced."""

    text: list[str] = field(default_factory=list)
    calls: dict[int, dict[str, str]] = field(default_factory=dict)
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def answer(self) -> str:
        return "".join(self.text)

    def tool_calls(self) -> list[dict[str, Any]]:
        """The collected calls in the stored, OpenAI-compatible shape."""
        return [
            {
                "id": call["id"] or f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {"name": call["name"], "arguments": call["arguments"]},
            }
            for _, call in sorted(self.calls.items())
        ]


async def read_round(
    chunks: AsyncIterator[Any], state: RoundState, stream_usage: StreamUsage = "final_chunk"
) -> AsyncIterator[Event]:
    """Forward text as it arrives and collect tool-call pieces.

    The reasoning field is ignored. A chunk may carry no choices (the final
    usage chunk), so each field is read only when present. Usage is read as
    the provider reports it: on a final chunk, or on every chunk, where the
    last report counts. A provider that reports none is not read.
    """
    async for chunk in chunks:
        usage = getattr(chunk, "usage", None) if stream_usage != "none" else None
        if usage is not None:
            state.prompt_tokens = usage.prompt_tokens
            state.completion_tokens = usage.completion_tokens
        for choice in chunk.choices or []:
            delta = choice.delta
            if delta is not None and delta.content:
                state.text.append(delta.content)
                yield ("delta", {"text": delta.content})
            for piece in (delta.tool_calls if delta is not None else None) or []:
                call = state.calls.setdefault(piece.index, {"id": "", "name": "", "arguments": ""})
                if piece.id:
                    call["id"] = piece.id
                function = piece.function
                if function is not None and function.name and not call["name"]:
                    call["name"] = function.name
                    yield ("tool", {"name": function.name, "phase": "start"})
                if function is not None and function.arguments:
                    call["arguments"] += function.arguments
            if choice.finish_reason:
                state.finish_reason = choice.finish_reason


class BuiltinTools:
    """The two built-in tools, search_thoughts and propose_thought, for one
    turn (openspec mcp-connectors design decision 2). Their names have no
    prefix, so the model sees them as before connectors existed."""

    def __init__(
        self,
        session: AsyncSession,
        user: User,
        conversation: Conversation,
        config: ChatConfig,
        context: list[dict[str, Any]],
        filing: Filing,
        command: str | None = None,
        held_parts: list[dict[str, Any]] | None = None,
        settings: Settings | None = None,
        http_client: httpx2.AsyncClient | None = None,
        zone: ZoneInfo | None = None,
    ):
        self.session = session
        self.user = user
        self.conversation = conversation
        self.config = config
        # The turn's context, shared with Turn: a proposal drops the held note.
        self.context = context
        self.filing = filing
        self.command = command
        # The held proposal's parts the context's note lists, if any.
        self.held_parts = held_parts
        self.settings = settings or get_settings()
        self.http_client = http_client
        # The user's zone, read once from the request: the search tool's days
        # and the proposal's dates are in it (thought-dates design decision 3).
        self.zone = zone or ZoneInfo(DEFAULT_ZONE)
        # One proposal per turn: a second propose_thought call is refused.
        self._proposed = False
        # Set by a candidate round of the similar-thought check: the next
        # proposal call skips layer 2 (the turn's next round must make it).
        self._checked = False

    def definitions(self) -> list[dict[str, Any]]:
        return self.filing.tools

    def owns(self, name: str) -> bool:
        return name in (SEARCH_TOOL, PROPOSE_TOOL)

    def needs_approval(self, name: str, turn: TurnToolState) -> bool:
        return False

    def action_target(self, name: str) -> ActionTarget:
        raise NotImplementedError("the built-in tools never need approval")

    async def call(self, name: str, arguments: dict[str, Any], turn: TurnToolState) -> ToolOutcome:
        if name == SEARCH_TOOL:
            search = parse_search(arguments)
            found = await search_tool_result(
                self.session,
                self.user,
                search,
                settings=self.settings,
                config=self.config.search,
                conversation_id=self.conversation.id,
                http_client=self.http_client,
                zone=self.zone,
                refs=await refs_for(self.session, self.conversation, before_next_row=True),
            )
            return ToolOutcome(
                result=found.text,
                summary=(
                    f"Looked up your thoughts dated {search.days_text}"
                    if search.by_date_only
                    else f"Searched your thoughts for “{search.query}”"
                ),
                extra={"sources": found.sources},
                details={"sources": found.sources},
            )
        if self._proposed:
            return ToolOutcome(result=ALREADY_PROPOSED, summary="Already proposed in this answer")
        return await self._propose(arguments, turn)

    async def _propose(self, arguments: dict[str, Any], turn: TurnToolState) -> ToolOutcome:
        """A propose_thought call.

        The similar-thought check runs first (thought-appending design
        decision 4). When a new part has candidates, nothing is written: the
        result lists them by ref and the turn's next round must propose
        again, once, with no second candidate round. A candidate round writes
        no proposal, so the one-proposal rule still allows that call. In the
        last round the limit allows, no round is left for that call, so
        layer 2 is skipped and the proposal is written at once, with its
        strong matches named: the user always gets a card.
        """
        parts = parse_proposal(arguments, self.filing.categories, self.zone)
        refs = await refs_for(self.session, self.conversation, before_next_row=True)
        check = await check_parts(
            self.session,
            self.user,
            parts,
            refs,
            config=self.config,
            settings=self.settings,
            again=self._checked or turn.last_round,
            conversation_id=self.conversation.id,
            http_client=self.http_client,
        )
        if check.has_candidates:
            result, similar = candidates_note(
                parts, check, refs, self.config.filing.seen_summary_chars, self.zone
            )
            self._checked = True
            # After a candidate round the model proposes again, choosing
            # add_to or new for each part, so the user always gets a card.
            turn.force_tool = PROPOSE_TOOL
            return ToolOutcome(
                result=result, summary="Checked for similar thoughts", details={"similar": similar}
            )

        drop_held_note(self.context, self.held_parts)
        self.held_parts = None
        proposal, replaced = await write_proposal(
            self.session,
            self.conversation,
            with_similar([part.as_dict() for part in parts], check),
            await next_position(self.session, self.conversation),
            push=self.command == "push",
            refs=refs,
        )
        self._proposed = True
        return ToolOutcome(
            result=PROPOSAL_SHOWN,
            summary="Proposed a thought to file",
            details={"proposal_id": str(proposal.id)},
            events=[
                (
                    "proposal",
                    {
                        **proposal_payload(
                            proposal, await part_lookup(self.session, self.user, [proposal])
                        ),
                        # The earlier proposal whose card now shows as replaced.
                        "replaces": str(replaced) if replaced else None,
                    },
                )
            ],
        )

    async def aclose(self) -> None:
        pass


class Turn:
    """Runs the tool loop for one message and stores what it produces."""

    def __init__(
        self,
        session: AsyncSession,
        user: User,
        conversation: Conversation,
        call: ModelCall,
        config: ChatConfig,
        context: list[dict[str, Any]],
        providers: list[ToolProvider],
        forced_tool: dict[str, Any] | None = None,
        tool_rounds: int | None = None,
    ):
        self.session = session
        self.user = user
        self.conversation = conversation
        self.call = call
        self.config = config
        self.context = context
        # The built-in tools first, then one provider per connector that is on.
        self.providers = providers
        self.tools = [definition for provider in providers for definition in provider.definitions()]
        # Connector data from earlier turns is in this turn's context too.
        self.tool_state = TurnToolState(read_connector_data=holds_connector_data(context))
        self.forced_tool = forced_tool
        # Every round counts, whatever its tools: a search, a similar-thought
        # check, or a connector call.
        self.tool_rounds = tool_rounds or config.tool_rounds
        self._first_chunks: AsyncIterator[Any] | None = None
        # The count before this turn, so the soft limit is noted once per crossing.
        self._tokens_before = conversation.last_prompt_tokens
        # The round being read, until it is stored: an interrupted turn keeps its text.
        self._in_flight: RoundState | None = None
        # Set when the turn was cancelled (server shutdown): its settle step
        # stores the answer with `store_interrupted`.
        self.interrupted = False
        # Set once the turn's reason for ending is stored (the tool round limit).
        self._end_stored = False

    async def aclose(self) -> None:
        """Close what the providers opened (connector sessions). Every
        provider is closed even when one fails. Safe to call more than once."""
        for provider in self.providers:
            try:
                await provider.aclose()
            except Exception:
                logger.exception("Could not close a tool provider")

    def _options(self, round_number: int) -> dict[str, Any]:
        options: dict[str, Any] = {"tools": self.tools}
        if round_number == 0 and self.forced_tool is not None:
            options["tool_choice"] = self.forced_tool
        elif self.tool_state.force_tool is not None:
            # A provider asked for this round's tool (a proposal after a
            # similar-thought candidate round).
            options["tool_choice"] = forced_tool(self.tool_state.force_tool)
            self.tool_state.force_tool = None
        return options

    async def open(self) -> None:
        """Open the first model call. Raises before any byte of the answer is sent."""
        self._first_chunks = await self.call.stream(self.context, **self._options(0))

    async def _store(self, **fields: Any) -> Message:
        message = Message(
            conversation_id=self.conversation.id,
            position=await next_position(self.session, self.conversation),
            **fields,
        )
        self.session.add(message)
        await self.session.commit()
        return message

    async def events(self) -> AsyncIterator[Event]:
        try:
            async for event in self._rounds():
                yield event
        except asyncio.CancelledError:
            # Nothing is stored here: an await now could be cancelled again.
            # The settle step, which runs shielded, calls store_interrupted.
            self.interrupted = True
            raise
        except Exception as exc:
            await self._store_failed(exc)
            raise

    async def store_interrupted(self) -> None:
        """Store a cancelled turn's answer as failed with `answer_interrupted`.

        The text of the round in flight is kept. A round already stored keeps
        its text in its own message, so the failed answer is then empty. A
        turn whose answer is already stored needs nothing more (the same rule
        as the startup sweep). Call it from the shielded settle step only,
        before the session is committed.
        """
        if not self.interrupted:
            return
        # Read before the rollback, which expires every loaded object.
        conversation_id = self.conversation.id
        # The cancel may have hit a write part way.
        await self.session.rollback()
        last = await last_message(self.session, conversation_id)
        if last is None or ends_answered(last):
            return
        state = self._in_flight
        self.session.add(
            interrupted_answer(conversation_id, last.position + 1, state.answer if state else None)
        )
        await self.session.commit()

    async def _rounds(self) -> AsyncIterator[Event]:
        last_answer: Message | None = None
        for round_number in range(self.tool_rounds):
            self.tool_state.last_round = round_number == self.tool_rounds - 1
            if round_number == 0:
                assert self._first_chunks is not None, "open() first"
                chunks = self._first_chunks
            else:
                chunks = await self.call.stream(self.context, **self._options(round_number))

            state = RoundState()
            self._in_flight = state
            async for event in read_round(
                chunks, state, self.call.provider.capabilities.stream_usage
            ):
                yield event
            async for event in self._note_usage(state):
                yield event

            calls = state.tool_calls()
            if not calls:
                if state.finish_reason == "length" or not state.answer.strip():
                    await self._store(
                        role="assistant",
                        content=state.answer or None,
                        status="cut",
                        error_code="output_limit_reached",
                    )
                    raise output_limit_reached(thinking_only=not state.answer.strip())
                await self._store(role="assistant", content=state.answer, status="complete")
                async for event in self._suggest_compact():
                    yield event
                return

            last_answer = await self._store(
                role="assistant", content=state.answer or None, tool_calls=calls, status="complete"
            )
            self._in_flight = None
            self.context.append(
                {"role": "assistant", "content": state.answer, "tool_calls": calls}
            )
            for tool_call in calls:
                async for event in self._run_tool(tool_call, last_answer.position):
                    yield event

        if last_answer is not None:
            last_answer.error_code = "tool_loop_limit"
            await self.session.commit()
            self._end_stored = True
        raise tool_loop_limit()

    async def _note_usage(self, state: RoundState) -> AsyncIterator[Event]:
        """Store and send the round's prompt tokens for the meter, record the
        usage, and send the usage warning when it is due."""
        if state.prompt_tokens is not None:
            self.conversation.last_prompt_tokens = state.prompt_tokens
            info = await self.call.info()
            usage: dict[str, Any] = {
                "prompt_tokens": state.prompt_tokens,
                "completion_tokens": state.completion_tokens or 0,
            }
            if info is not None and info.context_length:
                usage["context_length"] = info.context_length
            yield ("usage", usage)
        recorded = await self._record_usage(state)
        if recorded is None:
            return
        notice = await usage_warning(self.session, self.user.id)
        if notice is not None:
            yield ("notice", notice)

    async def _record_usage(self, state: RoundState) -> UsageEvent | None:
        """Record the round's usage with the conversation.

        A conversation deleted while its turn ran makes this commit fail. The
        usage is then recorded without it, as a deleted conversation's
        records are kept, and the turn ends: there is nothing left to answer.
        """
        conversation_id = self.conversation.id
        try:
            return await record_usage(
                self.session,
                self.call,
                "chat",
                state.prompt_tokens,
                state.completion_tokens,
                conversation_id,
            )
        except Exception:
            await self.session.rollback()
            exists = await self.session.scalar(
                select(Conversation.id).where(Conversation.id == conversation_id)
            )
            if exists is not None:
                raise
        await record_usage(
            self.session, self.call, "chat", state.prompt_tokens, state.completion_tokens
        )
        raise not_found()

    async def _suggest_compact(self) -> AsyncIterator[Event]:
        info = await self.call.info()
        notice = compact_suggestion(
            self._tokens_before,
            self.conversation.last_prompt_tokens,
            info.context_length if info is not None else None,
            self.config,
        )
        if notice is not None:
            yield ("notice", notice)

    async def _store_failed(self, exc: Exception) -> None:
        """Store the answer of a turn that ended with `exc` as failed with its code.

        Whatever raised (reading a round, opening the next one, a tool, the
        usage record), the answer is stored as failed, with the text of the
        round in flight. Nothing is added when the last stored message is
        already an answer (a reply cut at the length limit, or a complete one
        before a later step failed) or the turn stored its own reason.
        """
        if self._end_stored:
            return
        try:
            # Read before the rollback, which expires every loaded object.
            conversation_id = self.conversation.id
            # The error may have hit a write part way.
            await self.session.rollback()
            last = await last_message(self.session, conversation_id)
            if last is None or ends_answered(last):
                return
            state = self._in_flight
            self.session.add(
                Message(
                    conversation_id=conversation_id,
                    position=last.position + 1,
                    role="assistant",
                    content=(state.answer if state else None) or None,
                    status="failed",
                    error_code=exc.code if isinstance(exc, ApiError) else "internal_error",
                )
            )
            await self.session.commit()
        except Exception:
            logger.exception("Could not store a failed answer")

    def _provider_for(self, name: str) -> ToolProvider:
        for provider in self.providers:
            if provider.owns(name):
                return provider
        raise ToolArgumentError(f"there is no tool named '{name}'")

    async def _hold(
        self, provider: ToolProvider, name: str, arguments: dict[str, Any]
    ) -> ToolOutcome:
        """Store the call as an action for the user to approve, instead of
        calling the server (decision 7). The row is committed with the tool
        message, whose position it takes."""
        target = provider.action_target(name)
        action = new_action(
            self.conversation.id,
            self.user.id,
            target,
            arguments,
            await next_position(self.session, self.conversation),
        )
        self.session.add(action)
        return ToolOutcome(
            result=ACTION_SHOWN,
            summary=f"{tool_label(name)} is waiting for your approval",
            details={"action_id": str(action.id)},
            events=[("action", action_payload(action, target.title))],
        )

    async def _run_tool(self, tool_call: dict[str, Any], position: int) -> AsyncIterator[Event]:
        name = tool_call["function"]["name"]
        try:
            arguments = tool_arguments(tool_call["function"]["arguments"])
            provider = self._provider_for(name)
            if provider.needs_approval(name, self.tool_state):
                outcome = await self._hold(provider, name, arguments)
            else:
                outcome = await provider.call(name, arguments, self.tool_state)
        except (ValueError, ToolArgumentError) as exc:
            # Sent back to the model, which gets another round to call it right.
            outcome = ToolOutcome(
                result=f"Error: {exc}. Call the tool again with valid arguments.",
                summary="The tool call was not valid",
            )
        except ApiError as exc:
            if exc.code != ErrorCode.VALIDATION_ERROR:
                raise
            outcome = ToolOutcome(
                result=f"Error: {exc.message}. Call the tool again with valid arguments.",
                summary="The tool call was not valid",
            )

        for event in outcome.events:
            yield event
        await self._store(
            role="tool", tool_call_id=tool_call["id"], content=outcome.result, details=outcome.details
        )
        self.context.append(
            {"role": "tool", "tool_call_id": tool_call["id"], "content": outcome.result}
        )
        end: dict[str, Any] = {"name": name, "phase": "end", "summary": outcome.summary}
        if outcome.failed:
            end["failed"] = True
        yield ("tool", {**end, **outcome.extra})
