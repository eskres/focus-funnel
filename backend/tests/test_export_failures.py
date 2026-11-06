"""A failure or a lost client ends the download, and every export logs one
end line (thought-export task 2.6, design decision 8)."""

import asyncio
import logging

import pytest

from app.thoughts import export
from app.thoughts.export import LIVE
from tests.export_helpers import (
    Download,
    assert_no_sentinel_logged,
    export_records,
    listen_before,
    seed_sentinel_thoughts,
    thoughts_queries,
)
from tests.thought_helpers import counted_queries


class QueryBroke(Exception):
    """Raised from the second batch's thoughts query."""


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.INFO, logger="app.thoughts.export")
    return caplog


@pytest.fixture
def closed(monkeypatch) -> list[str]:
    """Wrap the export's generator; its finally records that it was closed."""
    real = export.export_thoughts
    seen: list[str] = []

    async def wrapped(*args):
        try:
            async for batch in real(*args):
                yield batch
        finally:
            seen.append("closed")

    monkeypatch.setattr(export, "export_thoughts", wrapped)
    return seen


def completion_marker(format: str) -> str:
    return '"count"' if format == "json" else "End of export"


async def seeded(api) -> object:
    user_id = await api.user_id()
    await seed_sentinel_thoughts(api, user_id, 5)
    return user_id


@pytest.mark.parametrize("format", ["json", "markdown"])
async def test_a_failing_query_breaks_the_stream(async_api, logs, batch_of_two, format):
    api = async_api
    user_id = await seeded(api)
    seen = []

    def hook(statement):
        if thoughts_queries([statement]):
            seen.append(statement)
            if len(seen) == 2:
                raise QueryBroke("the database went away")

    remove = listen_before(hook)
    try:
        item = await Download(api.app, api.headers, format, hold=False).start().done()
    finally:
        remove()
    assert item.status == 200
    assert isinstance(item.error, QueryBroke)
    # The opening part and the first batch were sent, and never the last body message.
    assert item.parts == 2
    assert not item.ended
    assert not any(
        m.get("more_body") is False
        for m in item.messages
        if m["type"] == "http.response.body"
    )
    assert completion_marker(format) not in item.text
    assert user_id not in LIVE
    assert export_records(logs) == [
        f"export ended user={user_id} format={format} thoughts=2 outcome=failed error=QueryBroke"
    ]
    assert_no_sentinel_logged(logs)


@pytest.mark.parametrize("format", ["json", "markdown"])
async def test_a_client_that_leaves_under_spec_2_3(
    async_api, logs, closed, batch_of_two, format
):
    api = async_api
    user_id = await seeded(api)

    async def on_body(item: Download, chunk: bytes, more: bool):
        if item.parts == 1 and chunk:
            # The first batch's part: the client goes away, and send waits
            # until the body task is cancelled.
            item.body += chunk
            item.parts += 1
            item.disconnect()
            await asyncio.Event().wait()

    with counted_queries() as statements:
        item = (
            await Download(api.app, api.headers, format, on_body=on_body).start().done()
        )
        queries_at_end = len(thoughts_queries(statements))
    assert item.error is None
    assert item.status == 200 and not item.ended
    assert completion_marker(format) not in item.text
    # One thoughts query, for the first batch; none after the client left.
    assert queries_at_end == 1
    assert closed == ["closed"]
    assert user_id not in LIVE
    assert export_records(logs) == [
        f"export ended user={user_id} format={format} thoughts=2 outcome=client_gone"
    ]
    after = await Download(api.app, api.headers, format, hold=False).start().done()
    assert after.status == 200 and completion_marker(format) in after.text
    assert_no_sentinel_logged(logs)


@pytest.mark.parametrize("format", ["json", "markdown"])
async def test_a_client_that_leaves_under_spec_2_4(
    async_api, logs, closed, batch_of_two, format
):
    api = async_api
    user_id = await seeded(api)

    async def on_body(item: Download, chunk: bytes, more: bool):
        if item.parts == 1 and chunk:
            raise OSError("connection reset by peer")

    with counted_queries() as statements:
        item = (
            await Download(
                api.app, api.headers, format, spec_version="2.4", on_body=on_body
            )
            .start()
            .done()
        )
    assert item.error is None
    assert item.status == 200 and not item.ended
    assert completion_marker(format) not in item.text
    assert len(thoughts_queries(statements)) == 1
    assert closed == ["closed"]
    assert user_id not in LIVE
    assert export_records(logs) == [
        f"export ended user={user_id} format={format} thoughts=2 outcome=client_gone"
    ]
    after = await Download(api.app, api.headers, format, hold=False).start().done()
    assert after.status == 200 and completion_marker(format) in after.text
    assert_no_sentinel_logged(logs)


@pytest.mark.parametrize("format", ["json", "markdown"])
async def test_a_client_that_leaves_on_the_closing_chunk(
    async_api, logs, batch_of_two, format
):
    api = async_api
    user_id = await seeded(api)
    marker = completion_marker(format).encode()

    async def on_body(item: Download, chunk: bytes, more: bool):
        if marker in chunk:
            raise OSError("connection reset by peer")

    item = (
        await Download(
            api.app, api.headers, format, spec_version="2.4", on_body=on_body
        )
        .start()
        .done()
    )
    assert item.error is None and not item.ended
    complete = (
        await Download(api.app, api.headers, format, spec_version="2.4", hold=False)
        .start()
        .done()
    )
    assert complete.ended and marker.decode() in complete.text
    assert export_records(logs) == [
        f"export ended user={user_id} format={format} thoughts=5 outcome=client_gone",
        f"export ended user={user_id} format={format} thoughts=5 outcome=complete",
    ]
    assert_no_sentinel_logged(logs)
