"""Usage records: one row per model call, the monthly warning, and the spend cap.

A record holds the provider, the model, the tokens, and the estimated cost.
It never holds message text.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.model_call import ModelCall
from app.models import UsageEvent, UserSettings
from app.provider_models import ModelItem, ModelPrices

UsageKind = Literal["chat", "compact", "proposal", "test", "embed"]
CapUnit = Literal["usd", "tokens"]


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


def next_month_start(moment: datetime) -> date:
    """The first day of the month after `moment`'s, in UTC: 1 January after December."""
    if moment.month == 12:
        return date(moment.year + 1, 1, 1)
    return date(moment.year, moment.month + 1, 1)


# Not given: record_usage reads the model's prices with `call.info()`.
_UNSET: Any = object()


async def record_usage(
    session: AsyncSession,
    call: ModelCall,
    kind: UsageKind,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    conversation_id: uuid.UUID | None = None,
    *,
    info: ModelItem | None = _UNSET,
) -> UsageEvent | None:
    """Store one call's usage and commit it.

    A call with no reported tokens is not recorded, except on a provider that
    never reports them: its calls are recorded with the tokens and the cost
    unknown. A chat turn passes the model's `info` its route already read, so
    no step of a turn fetches the model list (design decision 4); `None`
    there means the list could not be read and the cost is unknown.
    """
    if call.user_id is None:
        return None
    if prompt_tokens is None and call.reports_usage:
        return None
    if info is _UNSET:
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


@dataclass(frozen=True)
class CapState:
    """The user's monthly spend cap and where this month stands against it."""

    unit: CapUnit
    amount: Decimal
    # The month's sum in the cap's unit: estimated dollars or tokens.
    used: Decimal
    reached: bool
    resets_on: date

    def payload(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "amount": int(self.amount) if self.unit == "tokens" else float(self.amount),
            "reached": self.reached,
            "resets_on": self.resets_on,
        }


async def cap_state(
    session: AsyncSession, user_id: uuid.UUID, moment: datetime | None = None
) -> CapState | None:
    """The cap and the month's sum in its unit, or None when the user has no cap.

    The cap is read with a column select on every call, never through a
    `UserSettings` instance: the session may already hold that row, loaded
    before a cap was saved from another session, and a column select does not
    go through the identity map. A dollar cap sums the estimated costs, where
    unknown costs add nothing; a token cap sums the known tokens. Every kind
    of usage row counts. The cap is reached when the sum is equal to or above
    it.
    """
    row = (
        await session.execute(
            select(UserSettings.cap_unit, UserSettings.cap_amount).where(
                UserSettings.user_id == user_id
            )
        )
    ).one_or_none()
    if row is None or row.cap_unit is None or row.cap_amount is None:
        return None
    moment = moment or utc_now()
    cost, tokens = await month_totals(session, user_id, moment)
    unit: CapUnit = "usd" if row.cap_unit == "usd" else "tokens"
    amount = Decimal(str(row.cap_amount))
    used = cost if unit == "usd" else Decimal(tokens)
    return CapState(
        unit=unit,
        amount=amount,
        used=used,
        reached=used >= amount,
        resets_on=next_month_start(moment),
    )
