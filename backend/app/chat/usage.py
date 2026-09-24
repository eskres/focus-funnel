"""Usage records: one row per model call, and the monthly warning.

A record holds the provider, the model, the tokens, and the estimated cost.
It never holds message text.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.model_call import ModelCall
from app.models import UsageEvent, UserSettings
from app.provider_models import ModelPrices

UsageKind = Literal["chat", "compact", "proposal", "test", "embed"]


def estimate_cost(
    prices: ModelPrices | None, prompt_tokens: int | None, completion_tokens: int | None
) -> Decimal | None:
    """Tokens times the listed per-token prices (USD per token), or None when unknown."""
    if prices is None or prompt_tokens is None or completion_tokens is None:
        return None
    return Decimal(prices.prompt) * prompt_tokens + Decimal(prices.completion) * completion_tokens


def utc_now() -> datetime:
    return datetime.now(UTC)


def month_start(moment: datetime) -> datetime:
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def record_usage(
    session: AsyncSession,
    call: ModelCall,
    kind: UsageKind,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    conversation_id: uuid.UUID | None = None,
) -> UsageEvent | None:
    """Store one call's usage and commit it.

    A call with no reported tokens is not recorded, except on a provider that
    never reports them: its calls are recorded with the tokens and the cost
    unknown.
    """
    if call.user_id is None:
        return None
    if prompt_tokens is None and call.reports_usage:
        return None
    info = await call.info()
    event = UsageEvent(
        user_id=call.user_id,
        conversation_id=conversation_id,
        kind=kind,
        provider_id=call.provider.id,
        model=call.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens if prompt_tokens is not None else None,
        cost_usd=estimate_cost(info.prices if info else None, prompt_tokens, completion_tokens),
        created_at=utc_now(),
    )
    session.add(event)
    await session.commit()
    return event


def completion_usage(completion: Any) -> tuple[int | None, int | None]:
    """The token counts of a non-streamed completion, when it reports them."""
    usage = getattr(completion, "usage", None)
    if usage is None:
        return None, None
    return usage.prompt_tokens, usage.completion_tokens


async def month_totals(
    session: AsyncSession, user_id: uuid.UUID, moment: datetime | None = None
) -> tuple[Decimal, int]:
    """The estimated dollars and the tokens of the month so far, in UTC."""
    since = month_start(moment or utc_now())
    cost, prompt, completion = (
        await session.execute(
            select(
                func.coalesce(func.sum(UsageEvent.cost_usd), 0),
                func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
                func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            ).where(UsageEvent.user_id == user_id, UsageEvent.created_at >= since)
        )
    ).one()
    return Decimal(str(cost)), int(prompt) + int(completion)


def warning_reached(settings: UserSettings | None, cost: Decimal, tokens: int) -> bool:
    if settings is None or settings.warning_unit is None or settings.warning_amount is None:
        return False
    total = cost if settings.warning_unit == "usd" else Decimal(tokens)
    return total >= settings.warning_amount


def threshold_payload(settings: UserSettings) -> dict[str, Any]:
    amount = settings.warning_amount
    return {
        "unit": settings.warning_unit,
        "amount": int(amount) if settings.warning_unit == "tokens" else float(amount),
    }


async def usage_warning(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any] | None:
    """The usage_warning notice, once per month, when the month reaches the threshold.

    The month is stored when the notice is sent, so it is not sent again that
    month. The warning never blocks the chat.
    """
    settings = await session.get(UserSettings, user_id)
    if settings is None or settings.warning_unit is None:
        return None
    moment = utc_now()
    this_month = moment.strftime("%Y-%m")
    if settings.warning_notified_month == this_month:
        return None
    cost, tokens = await month_totals(session, user_id, moment)
    if not warning_reached(settings, cost, tokens):
        return None
    settings.warning_notified_month = this_month
    await session.commit()
    return {
        "kind": "usage_warning",
        **threshold_payload(settings),
        "month_cost_usd": float(cost),
        "month_tokens": tokens,
    }
