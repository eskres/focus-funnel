"""GET /api/usage: the user's estimated spend per day, per model, and this month.

PUT /api/usage/cap: the user's monthly spend cap.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.chat.loadout import get_user_settings
from app.chat.usage import (
    cap_state,
    month_start,
    threshold_payload,
    utc_now,
    warning_reached,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.models import ProviderKey, UsageEvent, User, UserSettings
from app.providers import resolve_provider

router = APIRouter(prefix="/api/usage")


class Totals(BaseModel):
    cost_usd: float
    tokens: int
    # Calls whose cost is unknown: no listed price, or no reported tokens.
    unknown_cost_calls: int
    calls: int


class DayUsage(Totals):
    date: date


class ModelUsage(Totals):
    provider_id: str
    model: str


class MonthUsage(Totals):
    start: date


class WarningState(BaseModel):
    unit: str
    amount: float
    reached: bool


class CapState(BaseModel):
    unit: Literal["usd", "tokens"]
    amount: float
    reached: bool
    # The first day of the next month in UTC, when the month's sum starts again.
    resets_on: date


class SpendCap(BaseModel):
    """A monthly spend cap, in estimated dollars or in tokens."""

    unit: Literal["usd", "tokens"]
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=6)

    @model_validator(mode="after")
    def _whole_tokens(self) -> "SpendCap":
        # Tokens are whole: a cap is shown and named as a whole number, so
        # it must be the number the check compares (design decision 31).
        if self.unit == "tokens" and self.amount != self.amount.to_integral_value():
            raise ValueError("A token cap needs a whole number.")
        return self


class SaveSpendCap(BaseModel):
    # Required: null removes the cap.
    cap: SpendCap | None


class SpendCapResponse(BaseModel):
    cap: CapState | None


class ProviderConsole(BaseModel):
    provider_id: str
    label: str
    url: str


class UsageReport(BaseModel):
    days: list[DayUsage]
    by_model: list[ModelUsage]
    month: MonthUsage
    warning: WarningState | None
    cap: CapState | None
    consoles: list[ProviderConsole]


class _Sum:
    def __init__(self) -> None:
        self.cost = Decimal(0)
        self.tokens = 0
        self.unknown = 0
        self.calls = 0

    def add(self, event: UsageEvent) -> None:
        self.calls += 1
        self.tokens += (event.prompt_tokens or 0) + (event.completion_tokens or 0)
        if event.cost_usd is None:
            self.unknown += 1
        else:
            self.cost += event.cost_usd

    def totals(self) -> dict:
        return {
            "cost_usd": float(self.cost),
            "tokens": self.tokens,
            "unknown_cost_calls": self.unknown,
            "calls": self.calls,
        }


def _as_utc(moment: datetime) -> datetime:
    # SQLite returns the stored UTC time without its zone.
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


@router.get("", response_model=UsageReport)
async def read_usage(
    days: int = Query(default=30, ge=1, le=366),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UsageReport:
    """Daily totals in UTC for the last `days` days, oldest first, with every
    day present; the split by model over the same days; and the month to date."""
    now = utc_now()
    today = now.date()
    first_day = today - timedelta(days=days - 1)
    period_start = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)
    this_month = month_start(now)
    since = min(period_start, this_month)

    events = (
        await session.execute(
            select(UsageEvent)
            .where(UsageEvent.user_id == user.id, UsageEvent.created_at >= since)
            .order_by(UsageEvent.created_at)
        )
    ).scalars()

    per_day = {first_day + timedelta(days=n): _Sum() for n in range(days)}
    per_model: dict[tuple[str, str], _Sum] = {}
    month = _Sum()
    for event in events:
        created = _as_utc(event.created_at)
        if created >= this_month:
            month.add(event)
        if created >= period_start:
            per_day[created.date()].add(event)
            per_model.setdefault((event.provider_id, event.model), _Sum()).add(event)

    by_model = sorted(
        (
            ModelUsage(provider_id=provider_id, model=model, **total.totals())
            for (provider_id, model), total in per_model.items()
        ),
        key=lambda row: (-row.cost_usd, -row.tokens, row.model),
    )

    user_settings = await get_user_settings(session, user)
    warning = None
    if user_settings is not None and user_settings.warning_unit is not None:
        warning = WarningState(
            **threshold_payload(user_settings),
            reached=warning_reached(user_settings, month.cost, month.tokens),
        )

    cap = await cap_state(session, user.id, now)

    return UsageReport(
        days=[DayUsage(date=day, **total.totals()) for day, total in per_day.items()],
        by_model=by_model,
        month=MonthUsage(start=this_month.date(), **month.totals()),
        warning=warning,
        cap=CapState(**cap.payload()) if cap is not None else None,
        consoles=await _consoles(session, user, settings),
    )


@router.put("/cap", response_model=SpendCapResponse)
async def save_cap(
    body: SaveSpendCap,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SpendCapResponse:
    """Save or remove the caller's monthly spend cap, and nothing else.

    It touches only the two cap columns. A user with no `user_settings` row
    gets one with every other column null; removing a cap that was never set
    creates nothing.
    """
    user_settings = await get_user_settings(session, user)
    if user_settings is None:
        if body.cap is None:
            return SpendCapResponse(cap=None)
        user_settings = UserSettings(user_id=user.id)
        session.add(user_settings)
    user_settings.cap_unit = body.cap.unit if body.cap is not None else None
    user_settings.cap_amount = body.cap.amount if body.cap is not None else None
    await session.commit()
    cap = await cap_state(session, user.id)
    return SpendCapResponse(cap=CapState(**cap.payload()) if cap is not None else None)


async def _consoles(session: AsyncSession, user: User, settings: Settings) -> list[ProviderConsole]:
    """The balance pages of the providers the user has saved a key for."""
    rows = (
        await session.execute(
            select(ProviderKey).where(ProviderKey.user_id == user.id).order_by(ProviderKey.provider_id)
        )
    ).scalars()
    consoles = []
    for row in rows:
        try:
            provider = resolve_provider(row.provider_id, settings, row)
        except Exception:
            continue
        if provider.console_url:
            consoles.append(
                ProviderConsole(provider_id=provider.id, label=provider.label, url=provider.console_url)
            )
    return consoles
