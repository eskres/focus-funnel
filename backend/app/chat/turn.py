"""One chat turn: stream the model's answer, run its tools, and store it all.

The first model call is opened before the response starts, so its failures
are ordinary error responses. Everything after that arrives as events.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.actions import ACTION_SHOWN, ActionTarget, action_payload, new_action
from app.chat.config import ChatConfig
from app.chat.context import compact_suggestion
from app.chat.conversations import next_position
from app.chat.model_call import ModelCall
from app.chat.prompt import PROPOSE_TOOL, SEARCH_TOOL, drop_held_note, tool_arguments
from app.chat.proposal import Filing, proposal_payload, write_proposal
from app.chat.sse import Event
from app.chat.tool_providers import ToolOutcome, ToolProvider, TurnToolState, tool_label
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
from app.models import Conversation, Message, User
from app.provider_config import StreamUsage

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
        # One proposal per turn: a second propose_thought call is refused.
        self._proposed = False

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
            )
            return ToolOutcome(
                result=found.text,
                summary=f"Searched your thoughts for “{search.query}”",
                extra={"sources": found.sources},
                details={"sources": found.sources},
            )
        if self._proposed:
            return ToolOutcome(result=ALREADY_PROPOSED, summary="Already proposed in this answer")
        parts = parse_proposal(arguments, self.filing.categories)
        drop_held_note(self.context, self.held_parts)
        self.held_parts = None
        proposal, replaced = await write_proposal(
            self.session,
            self.conversation,
            [part.as_dict() for part in parts],
            await next_position(self.session, self.conversation),
            push=self.command == "push",
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
                        **proposal_payload(proposal),
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
        self.tool_state = TurnToolState()
        self.forced_tool = forced_tool
        self.tool_rounds = tool_rounds or config.tool_rounds
        self._first_chunks: AsyncIterator[Any] | None = None
        # The count before this turn, so the soft limit is noted once per crossing.
        self._tokens_before = conversation.last_prompt_tokens

    async def aclose(self) -> None:
        """Close what the providers opened (connector sessions). Every
        provider is closed even when one fails."""
        for provider in self.providers:
            try:
                await provider.aclose()
            except Exception:
                logger.exception("Could not close a tool provider")

    def _options(self, round_number: int) -> dict[str, Any]:
        options: dict[str, Any] = {"tools": self.tools}
        if round_number == 0 and self.forced_tool is not None:
            options["tool_choice"] = self.forced_tool
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
        last_answer: Message | None = None
        for round_number in range(self.tool_rounds):
            if round_number == 0:
                assert self._first_chunks is not None, "open() first"
                chunks = self._first_chunks
            else:
                chunks = await self.call.stream(self.context, **self._options(round_number))

            state = RoundState()
            try:
                async for event in read_round(
                    chunks, state, self.call.provider.capabilities.stream_usage
                ):
                    yield event
            except Exception as exc:
                await self._store_failed(state, exc)
                raise
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
            self.context.append(
                {"role": "assistant", "content": state.answer, "tool_calls": calls}
            )
            for tool_call in calls:
                async for event in self._run_tool(tool_call, last_answer.position):
                    yield event

        if last_answer is not None:
            last_answer.error_code = "tool_loop_limit"
            await self.session.commit()
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
        recorded = await record_usage(
            self.session,
            self.call,
            "chat",
            state.prompt_tokens,
            state.completion_tokens,
            self.conversation.id,
        )
        if recorded is None:
            return
        notice = await usage_warning(self.session, self.user.id)
        if notice is not None:
            yield ("notice", notice)

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

    async def _store_failed(self, state: RoundState, exc: Exception) -> None:
        try:
            await self._store(
                role="assistant",
                content=state.answer or None,
                status="failed",
                error_code=exc.code if isinstance(exc, ApiError) else "internal_error",
            )
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
