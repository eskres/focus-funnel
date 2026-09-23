"""Test: a short prompt, then a one-tool probe, against one model and effort."""

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ChatConfig
from app.chat.loadout import temperature_for
from app.chat.model_call import open_model_call
from app.config import Settings
from app.errors import ApiError, ErrorCode, model_unsupported
from app.models import User
from app.provider_config import ProviderPreset

TEST_PROMPT = "Say in one short sentence that you are ready."
PROBE_PROMPT = "Call the ping tool now."
PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Answers pong. Call it when asked to.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def empty_answer(model: str, effort: str | None) -> ApiError:
    with_effort = f" with reasoning effort '{effort}'" if effort else ""
    return ApiError(
        400,
        ErrorCode.MODEL_UNSUPPORTED,
        f"The model '{model}' returned an empty answer{with_effort}. "
        "Try another effort or another model.",
    )


async def run_model_test(
    session: AsyncSession,
    user: User,
    provider: ProviderPreset,
    model: str,
    effort: str | None,
    *,
    config: ChatConfig,
    settings: Settings,
    http_client: httpx2.AsyncClient | None = None,
) -> str:
    """Return a success message, or raise the reason the model failed."""
    call = await open_model_call(
        session,
        user,
        provider,
        model,
        temperature=await temperature_for(session, user, config),
        max_tokens=config.reply_max_tokens,
        reasoning_effort=effort,
        settings=settings,
        http_client=http_client,
    )
    try:
        answer = await call.complete([{"role": "user", "content": TEST_PROMPT}])
        choice = answer.choices[0] if answer.choices else None
        if choice is None or not (choice.message.content or "").strip():
            raise empty_answer(model, effort)

        probe = await call.complete(
            [{"role": "user", "content": PROBE_PROMPT}], tools=[PROBE_TOOL]
        )
        called = probe.choices and probe.choices[0].message.tool_calls
        if not called:
            raise model_unsupported(model, "tool calling: it ignored the probe tool")
    finally:
        await call.aclose()
    return f"{model} answered and called the probe tool."
