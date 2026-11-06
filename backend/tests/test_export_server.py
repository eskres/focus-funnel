"""A broken stream through a real uvicorn server (thought-export task 2.8,
design decision 8).

The server runs on the test's own event loop with `log_config=None`, so
uvicorn applies no logging config and its records reach the root logger,
where caplog listens.
"""

import asyncio
import logging
import socket

import httpx
import pytest
import uvicorn
from sqlalchemy.ext.asyncio import AsyncSession

from app.thoughts import export
from app.thoughts.export import stop_exports
from tests.export_helpers import listen_before, seed_sentinel_thoughts, thoughts_queries

pytestmark = pytest.mark.postgres


class QueryBroke(Exception):
    pass


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def read_until_broken(
    response, first_part_seen: asyncio.Event
) -> tuple[bytes, Exception | None]:
    received = b""
    try:
        async for chunk in response.aiter_raw():
            received += chunk
            if b'"title"' in received:
                first_part_seen.set()
    except Exception as exc:  # noqa: BLE001 - the test inspects it
        return received, exc
    return received, None


def messages(caplog, logger: str) -> list[str]:
    return [r.getMessage().strip() for r in caplog.records if r.name == logger]


async def test_a_broken_stream_through_uvicorn(
    async_api, caplog, monkeypatch, batch_of_two
):
    api = async_api
    user_id = await api.user_id()
    await seed_sentinel_thoughts(api, user_id, 5)
    monkeypatch.setattr(logging.getLogger("uvicorn"), "propagate", True)
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    caplog.set_level(logging.INFO, logger="app.thoughts.export")

    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(api.app, host="127.0.0.1", port=port, log_config=None)
    )
    serving = asyncio.ensure_future(server.serve())
    try:
        for _ in range(200):
            if server.started or serving.done():
                break
            await asyncio.sleep(0.05)
        assert server.started, "uvicorn did not start"

        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", trust_env=False
        ) as http:
            # 1. The second batch's thoughts query raises.
            seen = []

            def hook(statement):
                if thoughts_queries([statement]):
                    seen.append(statement)
                    if len(seen) == 2:
                        raise QueryBroke("the database went away")

            remove = listen_before(hook)
            try:
                async with http.stream(
                    "GET",
                    "/api/me/export",
                    params={"format": "json"},
                    headers=api.headers,
                ) as response:
                    assert response.status_code == 200
                    first = asyncio.Event()
                    received, error = await read_until_broken(response, first)
            finally:
                remove()
            assert first.is_set(), received
            assert isinstance(error, httpx.RemoteProtocolError), error
            assert b'"count"' not in received
            await asyncio.sleep(0.1)
            assert "Exception in ASGI application" in messages(caplog, "uvicorn.error")

            # 2. The second batch's thoughts query waits; a delete stops the export meanwhile.
            caplog.clear()
            marked: list[object] = []
            reached = asyncio.Event()
            go_on = asyncio.Event()
            real_query = export._thoughts_query
            real_execute = AsyncSession.execute

            def marking(*args):
                query = real_query(*args)
                marked.append(query)
                return query

            async def waiting(self, statement, *args, **kwargs):
                if len(marked) == 2 and statement is marked[1]:
                    reached.set()
                    await go_on.wait()
                return await real_execute(self, statement, *args, **kwargs)

            monkeypatch.setattr(export, "_thoughts_query", marking)
            monkeypatch.setattr(AsyncSession, "execute", waiting)
            async with http.stream(
                "GET", "/api/me/export", params={"format": "json"}, headers=api.headers
            ) as response:
                assert response.status_code == 200
                first = asyncio.Event()
                reader = asyncio.ensure_future(read_until_broken(response, first))
                await asyncio.wait_for(first.wait(), 10)
                await asyncio.wait_for(reached.wait(), 10)
                stop_exports(user_id)
                go_on.set()
                received, error = await asyncio.wait_for(reader, 10)
            assert isinstance(error, httpx.RemoteProtocolError), error
            assert b'"count"' not in received
            await asyncio.sleep(0.1)
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)

    exports = messages(caplog, "app.thoughts.export")
    assert exports == [
        f"export ended user={user_id} format=json thoughts=2 outcome=failed error=ExportAborted"
    ]
    uvicorn_errors = messages(caplog, "uvicorn.error")
    assert "ASGI callable returned without completing response." in uvicorn_errors
    assert "Exception in ASGI application" not in uvicorn_errors
    assert not any(r.getMessage() == "Unhandled error" for r in caplog.records)
