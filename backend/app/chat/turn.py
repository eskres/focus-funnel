"""One chat turn: stream the model's answer, run its tools, and store it all.

The first model call is opened before the response starts, so its failures
are ordinary error responses. Everything after that arrives as events.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
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
    estimate_text_tokens,
    estimate_tokens,
    forced_tool,
    held_note_of,
    tool_arguments,
)
from app.chat.proposal import (
    Filing,
    part_lookup,
    proposal_payload,
    refs_for,
    resolve_marks,
    write_proposal,
)
from app.chat.running import TurnControl
from app.chat.similar import candidates_note, check_parts, with_similar
from app.chat.sse import Event
from app.chat.tool_providers import (
    ToolOutcome,
    ToolProvider,
    TurnToolState,
    holds_connector_data,
    tool_label,
)
from app.chat.usage import cap_state, record_usage, usage_warning
from app.chat.tools import (
    ALREADY_PROPOSED,
    PROPOSAL_SHOWN,
    PROPOSAL_SHOWN_STATUS,
    ToolArgumentError,
    ToolRefusal,
    parse_proposal,
    parse_search,
    search_tool_result,
)
from app.config import Settings, get_settings
from app.errors import (
    ApiError,
    ErrorCode,
    answer_stopped,
    output_limit_reached,
    spend_cap_reached,
    tool_loop_limit,
)
from app.models import Conversation, Message, UsageEvent, User
from app.ownership import not_found
from app.provider_config import StreamUsage
from app.provider_models import ModelItem
from app.thoughts.dates import DEFAULT_ZONE

logger = logging.getLogger(__name__)

# The tool message of a call a stop kept from starting (design decision 3).
NOT_RUN = "Not run: the user stopped the answer before this tool finished."


def may_have_run(name: str) -> str:
    """The tool message of a connector call a stop cut off while it ran: it
    may have reached its server (design decision 12)."""
    return f"Stopped while {name} was running. It may have run; check before running it again."


class StopRequested(Exception):
    """A check found the stop the user asked for (design decision 3). Turn
    turns it into the stopped answer; it never leaves `Turn.events`."""


@dataclass
class StopPoint:
    """Where the turn is, in plain values the stopped store reads after its
    rollback: never an ORM instance (design decision 3).

    `stream`: reading a round's stream, or opening a later round's call.
    `round`: the check before a later round's call. `tool`: a tool call of
    the round, `calls[index]`; `in_flight` while a connector call that may
    reach its server runs.
    """

    kind: str = "stream"
    calls: list[tuple[str, str]] = field(default_factory=list)
    index: int = 0
    in_flight: bool = False


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
        held_note: dict[str, Any] | None = None,
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
        # The note itself, the dict build_context() appended last: a written
        # proposal removes it by identity (thought-status design decision 6).
        self.held_note = held_note if held_note is not None else held_note_of(context, held_parts)
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

    def reaches_server(self, name: str, turn: TurnToolState) -> bool:
        # Database queries and at most one embedding call with its own
        # timeout: always run to the end, never cut by a stop.
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
                summary=search.summary,
                extra={"sources": found.sources},
                details={"sources": found.sources},
            )
        if self._proposed:
            return ToolOutcome(result=ALREADY_PROPOSED, summary="Already proposed in this answer")
        return await self._propose(arguments, turn)

    async def _propose(self, arguments: dict[str, Any], turn: TurnToolState) -> ToolOutcome:
        """A propose_thought call.

        Its marks are checked first, in one query, before the similar-thought
        check and any embedding call; a mark that cannot apply refuses the
        whole call with a ToolRefusal (thought-status design decisions 5
        and 6). The similar-thought check runs next, on the new parts only
        (thought-appending design decision 4). When a new part has
        candidates, nothing is written: the result lists them by ref and the
        turn's next round must propose again, once, with no second candidate
        round. A candidate round writes no proposal, so the one-proposal rule
        still allows that call; a refused call does not count for the skip
        either. In the last round the limit allows, no round is left for
        that call, so layer 2 is skipped and the proposal is written at once,
        with its strong matches named: the user always gets a card.

        The held note is dropped, and the held parts cleared, only once a
        proposal row is written: a refusal or a candidate round keeps both.
        """
        parts = parse_proposal(arguments, self.filing.categories, self.zone)
        refs = await refs_for(self.session, self.conversation, before_next_row=True)
        marks = iter(
            await resolve_marks(
                self.session,
                self.user.id,
                refs,
                [part.mark for part in parts if part.mark is not None],
                sum(1 for part in parts if part.mark is None),
            )
        )
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

        stored = [next(marks) if part.mark is not None else part.as_dict() for part in parts]
        proposal, replaced = await write_proposal(
            self.session,
            self.conversation,
            with_similar(stored, check),
            await next_position(self.session, self.conversation.id),
            push=self.command == "push",
            refs=refs,
        )
        drop_held_note(self.context, self.held_note)
        self.held_note = None
        self.held_parts = None
        self._proposed = True
        marked = [bool(part.get("mark")) for part in proposal.parts]
        return ToolOutcome(
            result=PROPOSAL_SHOWN_STATUS if any(marked) else PROPOSAL_SHOWN,
            summary="Proposed marking a thought done" if all(marked) else "Proposed a thought to file",
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
        info: ModelItem | None = None,
    ):
        self.session = session
        self.user = user
        self.conversation = conversation
        # Kept as a plain value: a rollback expires `conversation`.
        self.conversation_id = conversation.id
        self.call = call
        # The model's context length and prices, as the route read them for
        # check_room: no step of the turn fetches the model list (design
        # decision 4). None when the list could not be read.
        self.info = info
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
        # Shared with the turn's registry entry, which sets stop_requested
        # and sends the cancel (design decisions 1 and 3).
        self.control = TurnControl()
        # Where a stop would land, for the stopped store.
        self._at = StopPoint()
        # The chunks of the round being read, closed when a check stops it.
        self._chunks: AsyncIterator[Any] | None = None

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
            conversation_id=self.conversation_id,
            position=await next_position(self.session, self.conversation_id),
            **fields,
        )
        self.session.add(message)
        await self.session.commit()
        return message

    async def events(self) -> AsyncIterator[Event]:
        try:
            async for event in self._rounds():
                yield event
        except StopRequested:
            # A check found the stop: nothing was cut part way.
            await self._end_stopped()
            raise answer_stopped() from None
        except asyncio.CancelledError:
            if self.control.cancel_reason != "stop":
                # Shutdown. Nothing is stored here: an await now could be
                # cancelled again. The settle step, which runs shielded,
                # calls store_interrupted.
                self.interrupted = True
                raise
            # The stop's cancel, sent only inside a region and only once
            # (design decision 1): the turn goes on to store what it has.
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
            await self._end_stopped()
            raise answer_stopped() from None
        except Exception as exc:
            await self._store_failed(exc)
            raise

    # --- Stop (design decisions 1, 3, 4, and 12) ---

    def _check_stop(self) -> None:
        """The synchronous stop check, before every region and tool call."""
        if self.control.stop_requested:
            raise StopRequested

    async def _interruptible(self, open_await: Callable[[], Awaitable[Any]]) -> Any:
        """Await `open_await()` as a region a stop may cancel.

        The check comes right before the flag is set, with no await between
        them: a stop that landed earlier is seen here, and one that lands
        later finds the flag set and cancels the task. The flag is cleared
        as soon as the await returns, so a cancel never lands in a store.
        """
        self._check_stop()
        self.control.interruptible = True
        try:
            return await open_await()
        finally:
            self.control.interruptible = False

    async def _guarded(self, chunks: AsyncIterator[Any]) -> AsyncIterator[Any]:
        """The model stream with every wait for the next chunk a region; each
        chunk is handed on with the flag cleared."""
        while True:
            try:
                chunk = await self._interruptible(lambda: anext(chunks))
            except StopAsyncIteration:
                return
            yield chunk

    async def _end_stopped(self) -> None:
        """Close the stream a check stopped, then store the stopped answer."""
        chunks, self._chunks = self._chunks, None
        if chunks is not None:
            try:
                # Ends the provider's response, so it sends no more.
                await chunks.aclose()  # type: ignore[attr-defined]
            except Exception:
                logger.exception("Could not close a stopped model stream")
        try:
            await self._store_stopped()
        except Exception:
            logger.exception("Could not store a stopped answer")
            await self.session.rollback()
        self._end_stored = True

    async def _store_stopped(self) -> None:
        """Store what a stopped turn leaves, from where the stop landed.

        Runs in the turn's own task, never shielded: nothing cancels it a
        second time. The values it needs are read before the rollback, which
        drops anything a cancelled connector call added and expires every
        loaded object; the conversation is then loaded again.
        """
        at = self._at
        state = self._in_flight if at.kind == "stream" else None
        conversation_id = self.conversation_id
        await self.session.rollback()
        await self.session.refresh(self.conversation)
        if state is not None:
            # The round in flight has no usage row yet (decision 4).
            await self._record_stopped_usage(state)
        position = await next_position(self.session, conversation_id)
        if at.kind == "tool":
            # Every tool call gets a result, as the next request needs.
            for offset, (call_id, name) in enumerate(at.calls[at.index :]):
                cut = offset == 0 and at.in_flight
                self.session.add(
                    Message(
                        conversation_id=conversation_id,
                        position=position,
                        role="tool",
                        tool_call_id=call_id,
                        content=may_have_run(name) if cut else NOT_RUN,
                        details={"stopped": True},
                    )
                )
                position += 1
        # Calls the model was still sending when the stream stopped are not
        # stored as calls; their names keep the chat's tool lines.
        cut_off = (
            [call["name"] for _, call in sorted(state.calls.items()) if call["name"]]
            if state is not None
            else []
        )
        self.session.add(
            Message(
                conversation_id=conversation_id,
                position=position,
                role="assistant",
                content=(state.answer or None) if state is not None else None,
                status="stopped",
                error_code=ErrorCode.ANSWER_STOPPED,
                details={"stopped_tools": cut_off} if cut_off else None,
            )
        )
        await self.session.commit()

    async def _record_stopped_usage(self, state: RoundState) -> None:
        """Record a stopped round from what the provider reported so far,
        else from estimates (design decision 4). A provider that reports no
        usage keeps the tokens unknown."""
        received = estimate_text_tokens(
            state.answer + "".join(call["arguments"] for _, call in sorted(state.calls.items()))
        )
        prompt: int | None
        completion: int | None
        if not self.call.reports_usage:
            prompt = completion = None
        elif state.prompt_tokens is not None:
            prompt = state.prompt_tokens
            completion = max(state.completion_tokens or 0, received)
        else:
            prompt = estimate_tokens(self.context, self.tools)
            completion = received
        await record_usage(
            self.session,
            self.call,
            "chat",
            prompt,
            completion,
            self.conversation_id,
            info=self.info,
        )

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
        conversation_id = self.conversation_id
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
            state = RoundState()
            if round_number == 0:
                assert self._first_chunks is not None, "open() first"
                chunks = self._first_chunks
                self._at = StopPoint("stream")
                self._in_flight = state
            else:
                assert last_answer is not None
                # The cap first: its query awaits, and a stop that lands
                # during it is still seen by the check after it.
                await self._check_cap(last_answer)
                self._at = StopPoint("round")
                self._check_stop()
                self._at = StopPoint("stream")
                self._in_flight = state
                options = self._options(round_number)
                chunks = await self._interruptible(
                    lambda: self.call.stream(self.context, **options)
                )

            self._chunks = chunks
            async for event in read_round(
                self._guarded(chunks), state, self.call.provider.capabilities.stream_usage
            ):
                yield event
            self._chunks = None
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
            named = [(call["id"], call["function"]["name"]) for call in calls]
            for index, tool_call in enumerate(calls):
                self._at = StopPoint("tool", named, index)
                self._check_stop()
                async for event in self._run_tool(tool_call, last_answer.position):
                    yield event

        if last_answer is not None:
            last_answer.error_code = "tool_loop_limit"
            await self.session.commit()
            self._end_stored = True
        raise tool_loop_limit()

    async def _check_cap(self, last_answer: Message) -> None:
        """End the turn before its next model call when the month reached the
        cap, as saved now: a cap set or lowered while the turn runs counts
        (design decision 10). The last round's answer, whose tool calls all
        have their results, keeps the code, so a reload shows the end."""
        state = await cap_state(self.session, self.user.id)
        if state is None or not state.reached:
            return
        last_answer.error_code = ErrorCode.SPEND_CAP_REACHED
        await self.session.commit()
        self._end_stored = True
        raise spend_cap_reached(state)

    async def _note_usage(self, state: RoundState) -> AsyncIterator[Event]:
        """Store and send the round's prompt tokens for the meter, record the
        usage, and send the usage warning when it is due."""
        if state.prompt_tokens is not None:
            self.conversation.last_prompt_tokens = state.prompt_tokens
            info = self.info
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
        conversation_id = self.conversation_id
        try:
            return await record_usage(
                self.session,
                self.call,
                "chat",
                state.prompt_tokens,
                state.completion_tokens,
                conversation_id,
                info=self.info,
            )
        except Exception:
            await self.session.rollback()
            exists = await self.session.scalar(
                select(Conversation.id).where(Conversation.id == conversation_id)
            )
            if exists is not None:
                raise
        await record_usage(
            self.session,
            self.call,
            "chat",
            state.prompt_tokens,
            state.completion_tokens,
            info=self.info,
        )
        raise not_found()

    async def _suggest_compact(self) -> AsyncIterator[Event]:
        info = self.info
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
            conversation_id = self.conversation_id
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
            self.conversation_id,
            self.user.id,
            target,
            arguments,
            await next_position(self.session, self.conversation_id),
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
            elif provider.reaches_server(name, self.tool_state):
                # A connector call that may reach its server: a region a
                # stop cancels, after which the call may have run (design
                # decision 12).
                self._check_stop()
                self._at.in_flight = True
                outcome = await self._interruptible(
                    lambda: provider.call(name, arguments, self.tool_state)
                )
                self._at.in_flight = False
            else:
                outcome = await provider.call(name, arguments, self.tool_state)
        except ToolRefusal as exc:
            # A mark that cannot apply: the text says why and what to do, so
            # it goes back as it is (thought-status design decision 6).
            outcome = ToolOutcome(result=str(exc), summary="Could not propose that change")
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

        # The chat's line is stored too, so a reload shows the same
        # (thought-status design decision 5). The commit also holds what the
        # provider added (a proposal, a pending action), before its card is
        # sent: a card the chat shows is always stored, and a stop during
        # the call or the commit still lets the card out (design decision 3).
        await self._store(
            role="tool",
            tool_call_id=tool_call["id"],
            content=outcome.result,
            details={**(outcome.details or {}), "summary": outcome.summary},
        )
        self.context.append(
            {"role": "tool", "tool_call_id": tool_call["id"], "content": outcome.result}
        )
        for event in outcome.events:
            yield event
        end: dict[str, Any] = {"name": name, "phase": "end", "summary": outcome.summary}
        if outcome.failed:
            end["failed"] = True
        yield ("tool", {**end, **outcome.extra})
