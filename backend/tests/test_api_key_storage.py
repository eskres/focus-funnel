import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.auth import get_jwks_cache
from app.db import create_engine
from app.main import app
from app.models import NebiusApiKey
from app.nebius import get_nebius_http_client
from tests.conftest import FakeNebius, status

API_KEY = "nb-plaintext-must-not-be-stored-7c1d"


@pytest.fixture
def client(test_database_url, jwks_cache, settings_env):
    settings_env.setenv("NEBIUS_BASE_URL", "https://nebius.test/v1/")
    fake = FakeNebius(status(200, {"object": "list", "data": []}))
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    app.dependency_overrides[get_nebius_http_client] = lambda: fake.http_client()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def read_raw_rows(url: str) -> list[dict]:
    async def read():
        engine = create_engine(url, poolclass=NullPool)
        async with engine.connect() as connection:
            rows = (await connection.execute(select(NebiusApiKey.__table__))).mappings().all()
        await engine.dispose()
        return [dict(row) for row in rows]

    return asyncio.run(read())


def test_stored_row_has_no_plaintext_key(client, test_database_url, make_token):
    headers = {"Authorization": f"Bearer {make_token(sub='auth0|storage')}"}
    response = client.put("/api/settings/api-key", headers=headers, json={"api_key": API_KEY})
    assert response.status_code == 200

    rows = read_raw_rows(test_database_url)
    assert len(rows) == 1
    row = rows[0]
    assert row["last4"] == API_KEY[-4:]
    for column, value in row.items():
        if isinstance(value, (bytes, bytearray, memoryview)):
            assert API_KEY.encode() not in bytes(value), column
        else:
            assert API_KEY not in str(value), column


def test_sqlite_database_file_has_no_plaintext_key(client, test_database_url, make_token):
    url = make_url(test_database_url)
    if url.get_backend_name() != "sqlite":
        pytest.skip("file scan applies to SQLite only")

    headers = {"Authorization": f"Bearer {make_token(sub='auth0|storage-file')}"}
    assert client.put(
        "/api/settings/api-key", headers=headers, json={"api_key": API_KEY}
    ).status_code == 200

    database_file = Path(url.database)
    contents = b"".join(
        path.read_bytes()
        for path in (database_file, Path(f"{database_file}-wal"), Path(f"{database_file}-journal"))
        if path.exists()
    )
    assert contents, "the database file must exist and hold data"
    assert API_KEY.encode() not in contents
