"""One chat turn: stream the model's answer, run its tools, and store it all.

The first model call is opened before the response starts, so its failures
are ordinary error responses. Everything after that arrives as events.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ChatConfig
from app.chat.conversations import next_position
from app.chat.model_call import ModelCall
from app.chat.prompt import PROPOSE_TOOL, SEARCH_TOOL, TOOLS, tool_arguments
from app.chat.sse import Event
from app.chat.tools import (
    PROPOSAL_SHOWN,
    ToolArgumentError,
    parse_proposal,
    search_thoughts,
)
from app.errors import ApiError, output_limit_reached, tool_loop_limit
from app.models import Conversation, Message, User

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


async def read_round(chunks: AsyncIterator[Any], state: RoundState) -> AsyncIterator[Event]:
    """Forward text as it arrives and collect tool-call pieces.

    The reasoning field is ignored. A chunk may carry no choices (the final
    usage chunk), so each field is read only when present.
    """
    async for chunk in chunks:
        usage = getattr(chunk, "usage", None)
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
        forced_tool: dict[str, Any] | None = None,
    ):
        self.session = session
        self.user = user
        self.conversation = conversation
        self.call = call
        self.config = config
        self.context = context
        self.forced_tool = forced_tool
        self._first_chunks: AsyncIterator[Any] | None = None

    def _options(self, round_number: int) -> dict[str, Any]:
        options: dict[str, Any] = {"tools": TOOLS}
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
        for round_number in range(self.config.tool_rounds):
            if round_number == 0:
                assert self._first_chunks is not None, "open() first"
                chunks = self._first_chunks
            else:
                chunks = await self.call.stream(self.context, **self._options(round_number))

            state = RoundState()
            try:
                async for event in read_round(chunks, state):
                    yield event
            except Exception as exc:
                await self._store_failed(state, exc)
                raise
            self._note_usage(state)

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

    def _note_usage(self, state: RoundState) -> None:
        if state.prompt_tokens is not None:
            self.conversation.last_prompt_tokens = state.prompt_tokens

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

    async def _run_tool(self, tool_call: dict[str, Any], position: int) -> AsyncIterator[Event]:
        name = tool_call["function"]["name"]
        summary = ""
        try:
            arguments = tool_arguments(tool_call["function"]["arguments"])
            if name == SEARCH_TOOL:
                query = arguments.get("query")
                if not isinstance(query, str) or not query.strip():
                    raise ToolArgumentError("query must be a non-empty string")
                result = await search_thoughts(self.user, query.strip())
                summary = f"Searched your thoughts for “{query.strip()}”"
            elif name == PROPOSE_TOOL:
                proposal = parse_proposal(arguments)
                self.conversation.held_proposal = {**proposal.as_dict(), "position": position}
                yield ("proposal", proposal.as_dict())
                result = PROPOSAL_SHOWN
                summary = "Proposed a thought to file"
            else:
                raise ToolArgumentError(f"there is no tool named '{name}'")
        except (ValueError, ToolArgumentError) as exc:
            # Sent back to the model, which gets another round to call it right.
            result = f"Error: {exc}. Call the tool again with valid arguments."
            summary = "The tool call was not valid"

        await self._store(role="tool", tool_call_id=tool_call["id"], content=result)
        self.context.append({"role": "tool", "tool_call_id": tool_call["id"], "content": result})
        yield ("tool", {"name": name, "phase": "end", "summary": summary})
