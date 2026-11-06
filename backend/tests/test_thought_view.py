"""One shape for a thought (thought-export task 1.1): thought_view() and
addition_view() build the router's models. The GET answer's keys and
statement count are checked in test_thought_additions.py."""

from app.routers.thoughts import (
    AdditionOut,
    OriginOut,
    ThoughtOut,
    addition_view,
    thought_view,
)
from tests.test_thought_additions import DETAIL_KEYS


def test_the_two_views_build_the_router_models():
    import uuid
    from dataclasses import dataclass
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.thoughts.additions import AdditionOut as AdditionRow
    from app.thoughts.store import ThoughtOrigin

    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    ids = [uuid.uuid4() for _ in range(4)]
    row = AdditionRow(
        id=ids[0],
        added_at=now,
        undone=False,
        conversation_id=ids[1],
        conversation_title="Bike",
        proposal_id=ids[2],
    )

    @dataclass
    class Labelled:  # any row with these attributes, such as a labelled Row
        id: uuid.UUID
        added_at: datetime
        undone: bool
        conversation_id: uuid.UUID
        conversation_title: str
        proposal_id: uuid.UUID

    assert addition_view(row) == AdditionOut(**vars(row))
    assert addition_view(Labelled(**vars(row))) == AdditionOut(**vars(row))

    stored = SimpleNamespace(
        id=ids[3],
        title="Buy new bike lock",
        summary="Buy a lock.",
        tags=None,
        category=None,
        raw_text=None,
        starts_on=None,
        created_at=now,
        updated_at=now,
        status="open",
        status_changed_at=None,
    )
    origin = ThoughtOrigin(
        conversation_id=ids[1],
        conversation_title="Bike",
        archived=False,
        proposal_id=ids[2],
        proposed_at=now,
    )

    view = thought_view(stored, origin, [addition_view(row)])

    assert isinstance(view, ThoughtOut)
    assert set(view.model_dump()) == DETAIL_KEYS
    assert view.tags == []
    assert view.origin == OriginOut(**vars(origin))
    assert view.additions == [AdditionOut(**vars(row))]
    assert thought_view(stored, None, []).origin is None
