"""Driving the export over ASGI, and seeding thoughts for the export tests
(thought-export group 2).

httpx's ASGITransport reads whole responses, so it cannot hold a stream
after its first part. `Download` talks ASGI directly: its `send` can hold
after each body part until the test lets it go on, raise, or report a
disconnect, the way a slow or departing browser would.
"""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Engine

from app.models import Conversation, Proposal, Thought, ThoughtAddition, User

OnBody = Callable[["Download", bytes, bool], Awaitable[None]]

# Sentinels: no log record may hold them (design decision 8).
SENTINEL_TITLE = "QUOKKA-TITLE-SENTINEL"
SENTINEL_SUMMARY = "QUOKKA-SUMMARY-SENTINEL"
SENTINEL_RAW = "QUOKKA-RAW-SENTINEL"
SENTINELS = (SENTINEL_TITLE, SENTINEL_SUMMARY, SENTINEL_RAW)

EXPORT_PATH = "/api/me/export"


class Download:
    """One export request on the app, driven over ASGI.

    With `hold`, its `send` stops after each body part that has more to come
    until the test calls `step()` (go on to the next part) or `finish()` (run
    to the end). `on_body` replaces that behaviour for a test that needs its
    own `send`. `disconnect()` makes `receive` report the client gone.
    """

    def __init__(
        self,
        app,
        headers: dict[str, str],
        format: str | None = "json",
        *,
        hold: bool = True,
        spec_version: str = "2.3",
        on_body: OnBody | None = None,
    ):
        self.app = app
        self.headers = headers
        self.format = format
        self.holding = hold
        self.spec_version = spec_version
        self.on_body = on_body
        self.status: int | None = None
        self.response_headers: dict[str, str] = {}
        self.body = b""
        self.parts = 0
        self.messages: list[dict] = []
        self.ended = False  # a body message with more_body False was sent
        self.error: BaseException | None = None
        self.task: asyncio.Task | None = None
        self.gone = asyncio.Event()
        self._held = asyncio.Event()
        self._go = asyncio.Event()
        self._request_sent = False

    @property
    def text(self) -> str:
        return self.body.decode()

    def json(self) -> dict:
        return json.loads(self.body)

    async def receive(self) -> dict:
        if not self._request_sent:
            self._request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self.gone.wait()
        return {"type": "http.disconnect"}

    def disconnect(self) -> None:
        self.gone.set()

    async def send(self, message: dict) -> None:
        self.messages.append(message)
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.response_headers = {
                k.decode(): v.decode() for k, v in message["headers"]
            }
            return
        if message["type"] != "http.response.body":
            return
        chunk = message.get("body", b"")
        more = message.get("more_body", False)
        if self.on_body is not None:
            await self.on_body(self, chunk, more)
        self.body += chunk
        if chunk:
            self.parts += 1
        if not more:
            self.ended = True
            return
        if self.holding and self.on_body is None:
            self._held.set()
            await self._go.wait()
            self._go.clear()

    def scope(self) -> dict:
        query = f"format={self.format}".encode() if self.format is not None else b""
        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": self.spec_version},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": EXPORT_PATH,
            "raw_path": EXPORT_PATH.encode(),
            "query_string": query,
            "root_path": "",
            "headers": [
                (k.lower().encode(), v.encode()) for k, v in self.headers.items()
            ]
            + [(b"host", b"test")],
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
        }

    async def _run(self) -> None:
        try:
            await self.app(self.scope(), self.receive, self.send)
        except BaseException as exc:
            self.error = exc

    def start(self) -> "Download":
        self.task = asyncio.ensure_future(self._run())
        return self

    async def settled(self, timeout: float = 10) -> bool:
        """Wait until the export holds after a body part (True) or has ended."""
        waiter = asyncio.ensure_future(self._held.wait())
        try:
            await asyncio.wait(
                {waiter, self.task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            waiter.cancel()
        holding = self._held.is_set()
        self._held.clear()
        return holding

    async def held(self, timeout: float = 10) -> None:
        """Wait until the export holds after a body part."""
        assert await self.settled(timeout), (
            f"the export did not hold: status {self.status}, {self.text!r}"
        )

    def step(self) -> None:
        """Send the held part's successor, then hold again."""
        self._go.set()

    def finish(self) -> None:
        """Run to the end without holding."""
        self.holding = False
        self._go.set()

    async def done(self, timeout: float = 10) -> "Download":
        self.finish()
        await asyncio.wait_for(asyncio.shield(self.task), timeout)
        return self


async def download(app, headers, format: str | None = "json", **options) -> Download:
    """A whole export, not held."""
    return await Download(app, headers, format, hold=False, **options).start().done()


async def started(app, headers, format: str = "json", **options) -> Download:
    """An export held after its first body part (or ended, when refused)."""
    started = Download(app, headers, format, **options).start()
    await started.held()
    return started


def error_of(item: Download) -> dict:
    return item.json()["error"]


async def make_user(api, headers) -> uuid.UUID:
    response = await api.http.get("/api/me", headers=headers)
    assert response.status_code == 200, response.text
    return uuid.UUID(response.json()["id"])


BASE = datetime(2026, 10, 1, 9, 12, tzinfo=UTC)


async def seed_plain(
    api, user_id: uuid.UUID, count: int, *, start: datetime = BASE, **fields
) -> list[uuid.UUID]:
    """`count` plain thoughts titled `Thought <n>`, a minute apart; ids oldest first."""

    async def work(session):
        thoughts = [
            Thought(
                user_id=user_id,
                title=f"Thought {index}",
                summary=f"About thought {index}.",
                tags=[],
                created_at=start + timedelta(minutes=index),
                **fields,
            )
            for index in range(count)
        ]
        session.add_all(thoughts)
        await session.commit()
        return [thought.id for thought in thoughts]

    return await api.db(work)


async def seed_sentinel_thoughts(
    api, user_id: uuid.UUID, count: int
) -> list[uuid.UUID]:
    """`count` thoughts whose title, summary, and raw text hold the sentinels."""

    async def work(session):
        thoughts = [
            Thought(
                user_id=user_id,
                title=f"{SENTINEL_TITLE} {index}",
                summary=f"{SENTINEL_SUMMARY} {index}.",
                raw_text=f"Raw words {SENTINEL_RAW} {index}",
                tags=[],
                created_at=BASE + timedelta(minutes=index),
            )
            for index in range(count)
        ]
        session.add_all(thoughts)
        await session.commit()
        return [thought.id for thought in thoughts]

    return await api.db(work)


async def seed_everything(api, user_id: uuid.UUID) -> dict:
    """The "Everything a thought has" thought: a done task with tags, a date,
    an origin in the archived conversation `Weekend plans`, one addition from
    `Plumber chat`, and one undone addition. Returns the ids."""

    async def work(session):
        weekend = Conversation(
            user_id=user_id,
            title="Weekend plans",
            archived_at=datetime(2026, 10, 20, 8, 0, tzinfo=UTC),
        )
        plumber = Conversation(user_id=user_id, title="Plumber chat")
        session.add_all([weekend, plumber])
        await session.flush()
        origin = Proposal(
            conversation_id=weekend.id,
            user_id=user_id,
            position=1,
            from_position=0,
            to_position=0,
            raw_text="the kitchen tap leaks again, call the plumber on monday",
            parts=[{"title": "Call the plumber"}],
            created_at=datetime(2026, 10, 1, 9, 10, tzinfo=UTC),
        )
        added = Proposal(
            conversation_id=plumber.id,
            user_id=user_id,
            position=3,
            from_position=2,
            to_position=2,
            raw_text="he comes at nine",
            parts=[{"title": "Call the plumber"}],
        )
        undone = Proposal(
            conversation_id=plumber.id,
            user_id=user_id,
            position=5,
            from_position=4,
            to_position=4,
            raw_text="never mind",
            parts=[{"title": "Call the plumber"}],
        )
        session.add_all([origin, added, undone])
        await session.flush()
        thought = Thought(
            user_id=user_id,
            title="Call the plumber",
            summary="Call the plumber about the leaking kitchen tap.",
            raw_text="the kitchen tap leaks again, call the plumber on monday\n\nhe comes at nine",
            tags=["home", "weekend plans"],
            category="task",
            starts_on=date(2026, 11, 9),
            time_zone="Europe/Oslo",
            proposal_id=origin.id,
            status="done",
            status_changed_at=datetime(2026, 11, 4, 10, 15, tzinfo=UTC),
            created_at=datetime(2026, 10, 1, 9, 12, tzinfo=UTC),
            updated_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
        )
        session.add(thought)
        await session.flush()
        before = {
            "title": thought.title,
            "summary": "old",
            "tags": [],
            "category": None,
            "raw_text": "old",
        }
        session.add_all(
            [
                ThoughtAddition(
                    thought_id=thought.id,
                    user_id=user_id,
                    proposal_id=added.id,
                    from_position=2,
                    to_position=2,
                    added_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
                    after_updated_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
                    before=before,
                ),
                ThoughtAddition(
                    thought_id=thought.id,
                    user_id=user_id,
                    proposal_id=undone.id,
                    from_position=4,
                    to_position=4,
                    added_at=datetime(2026, 10, 11, 9, 0, tzinfo=UTC),
                    after_updated_at=datetime(2026, 10, 11, 9, 0, tzinfo=UTC),
                    before=before,
                    undone_at=datetime(2026, 10, 11, 10, 0, tzinfo=UTC),
                ),
            ]
        )
        await session.commit()
        return {
            "thought": thought.id,
            "weekend": weekend.id,
            "plumber": plumber.id,
            "origin": origin.id,
            "added": added.id,
            "undone": undone.id,
        }

    return await api.db(work)


async def updated_times(api, user_id: uuid.UUID) -> dict[uuid.UUID, datetime]:
    async def work(session):
        rows = await session.execute(
            select(Thought.id, Thought.updated_at).where(Thought.user_id == user_id)
        )
        return dict(rows.all())

    return await api.db(work)


async def demo_expiry(api, user_id: uuid.UUID) -> datetime:
    async def work(session):
        return (await session.get(User, user_id)).expires_at

    return await api.db(work)


class QueryWatch:
    """Run a hook when the export's thoughts query has run for the n-th time
    (an `after_cursor_execute` listener), or make it raise or wait first."""

    def __init__(self):
        self.statements: list[str] = []

    @staticmethod
    def is_thoughts_query(statement: str) -> bool:
        head = statement.split("FROM", 1)
        return (
            len(head) == 2
            and head[1].lstrip().startswith("thoughts")
            and "LIMIT" in statement
        )


def thoughts_queries(statements: list[str]) -> list[str]:
    """The export's thoughts queries among recorded statements."""
    return [s for s in statements if QueryWatch.is_thoughts_query(s)]


def additions_queries(statements: list[str]) -> list[str]:
    return [s for s in statements if "FROM thought_additions" in s]


def listen_after(hook: Callable[[str], None]):
    """Register `hook(statement)` on every engine's after_cursor_execute;
    returns the function that removes it."""

    def after(conn, cursor, statement, *args):
        hook(statement)

    event.listen(Engine, "after_cursor_execute", after)
    return lambda: event.remove(Engine, "after_cursor_execute", after)


def listen_before(hook: Callable[[str], None]):
    def before(conn, cursor, statement, *args):
        hook(statement)

    event.listen(Engine, "before_cursor_execute", before)
    return lambda: event.remove(Engine, "before_cursor_execute", before)


class Api:
    """The app on the test's own event loop: `http` for whole answers,
    `Download` for held ones."""

    def __init__(self, app, http, headers: dict[str, str]):
        self.app = app
        self.http = http
        self.headers = headers

    async def db(self, work):
        from app.db import get_sessionmaker

        async with get_sessionmaker()() as session:
            return await work(session)

    async def user_id(self, headers: dict[str, str] | None = None) -> uuid.UUID:
        return await make_user(self, headers or self.headers)

    async def get(self, path: str, headers: dict[str, str] | None = None, **params):
        return await self.http.get(path, headers=headers or self.headers, params=params)


@pytest.fixture
async def demo_visitor(test_database_url, settings_env):
    """The app in demo mode with one visitor's session."""
    import httpx

    from app.db import get_engine
    from app.main import app
    from tests.chat_helpers import PROVIDERS_FIXTURE

    settings_env.setenv("AUTH_MODE", "demo")
    settings_env.delenv("OIDC_ISSUER")
    settings_env.delenv("OIDC_CLIENT_ID")
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            started = await http.post("/api/demo/sessions")
            assert started.status_code == 201, started.text
            yield Api(
                app, http, {"Authorization": f"Bearer {started.json()['session']}"}
            )
    finally:
        await get_engine().dispose()


@pytest.fixture
def export_now(monkeypatch):
    """The export's clock at 2026-11-05 14:03:00 UTC."""
    from app.thoughts import export

    moment = datetime(2026, 11, 5, 14, 3, 0, tzinfo=UTC)
    monkeypatch.setattr(export, "utcnow", lambda: moment)
    return moment


@pytest.fixture
def lease_clock(monkeypatch):
    """The lease's monotonic clock, moved by hand: `lease_clock.move(61)`."""
    from app.thoughts import export

    class Clock:
        now = 1000.0

        def move(self, seconds: float) -> None:
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(export, "monotonic", lambda: clock.now)
    return clock


@pytest.fixture
def batch_of_two(monkeypatch):
    from app.thoughts import export

    monkeypatch.setattr(export, "EXPORT_BATCH", 2)


def export_records(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "app.thoughts.export"]


def assert_no_sentinel_logged(caplog) -> None:
    for record in caplog.records:
        text = record.getMessage() + (record.exc_text or "")
        for sentinel in SENTINELS:
            assert sentinel not in text, record
