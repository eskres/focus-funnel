"""The setup state, the setup token, and require_setup (self-hosting-setup tasks 2.3 and 2.4)."""

import asyncio
import hashlib
import hmac
import logging
import re

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import get_jwks_cache
from app.config import get_settings
from app.db import create_engine
from app.errors import register_error_handlers
from app.main import app
from app.models import SetupState, User
from app.setup import state as setup_state_module
from app.setup.state import hash_token, open_setup, require_setup
from tests.conftest import CACHED
from tests.test_provider_key_migration import run_alembic

TOKEN_LINE = re.compile(r"^Setup token: (\S+)$", re.MULTILINE)


def sessionmaker_for(url: str):
    return lambda: async_sessionmaker(create_engine(url, poolclass=NullPool), expire_on_commit=False)


def run(url: str, statement):
    async def main():
        engine = create_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(statement)
                return result.all() if result.returns_rows else None
        finally:
            await engine.dispose()

    return asyncio.run(main())


def setup_rows(url: str):
    return run(url, select(SetupState.id, SetupState.token_hash, SetupState.token_created_at,
                           SetupState.completed_at))


def call_open_setup(url: str) -> None:
    get_settings.cache_clear()
    asyncio.run(open_setup(get_settings(), sessionmaker_for(url)))


def printed_token(text: str) -> str:
    tokens = TOKEN_LINE.findall(text)
    assert len(tokens) == 1, text
    return tokens[0]


@pytest.fixture
def open_db(test_database_url, settings_env):
    """A database with the setup row as the migration leaves it, and setup turned on."""
    run(test_database_url, insert(SetupState).values(id=1))
    settings_env.setenv("SETUP_WIZARD", "true")
    settings_env.delenv("APP_BASE_URL", raising=False)
    return test_database_url


# open_setup()


def test_open_setup_prints_a_token_and_stores_its_hash(open_db, settings_env, capsys, caplog):
    settings_env.setenv("APP_BASE_URL", "https://focus.example.org/")
    caplog.set_level(logging.DEBUG)
    call_open_setup(open_db)
    captured = capsys.readouterr()
    assert captured.out == ""
    token = printed_token(captured.err)
    assert len(token) >= 32
    assert "Open https://focus.example.org/setup (the app's /setup, not Pocket ID's)" in captured.err
    [row] = setup_rows(open_db)
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in [str(value) for value in row]
    assert row.token_created_at is not None
    assert row.completed_at is None
    assert all(token not in record.getMessage() for record in caplog.records)


def test_open_setup_without_app_base_url_says_not_pocket_ids(open_db, capsys):
    call_open_setup(open_db)
    err = capsys.readouterr().err
    printed_token(err)
    assert "Open /setup on the app (port 3000 by default, not Pocket ID's /setup)" in err


def test_each_call_prints_a_new_token_and_replaces_the_hash(open_db, capsys):
    call_open_setup(open_db)
    first = printed_token(capsys.readouterr().err)
    call_open_setup(open_db)
    second = printed_token(capsys.readouterr().err)
    assert first != second
    [row] = setup_rows(open_db)
    assert row.token_hash == hash_token(second)


def test_finished_setup_prints_and_stores_nothing(open_db, capsys):
    run(open_db, update(SetupState).values(completed_at=_now()))
    call_open_setup(open_db)
    assert capsys.readouterr().err == ""
    [row] = setup_rows(open_db)
    assert row.token_hash is None


def test_setup_wizard_false_prints_and_stores_nothing(open_db, settings_env, capsys):
    settings_env.setenv("SETUP_WIZARD", "false")
    call_open_setup(open_db)
    assert capsys.readouterr().err == ""
    [row] = setup_rows(open_db)
    assert row.token_hash is None


def test_demo_mode_prints_and_stores_nothing(open_db, settings_env, capsys):
    settings_env.setenv("AUTH_MODE", "demo")
    settings_env.delenv("OIDC_ISSUER")
    settings_env.delenv("OIDC_CLIENT_ID")
    settings_env.delenv("SETUP_WIZARD")
    call_open_setup(open_db)
    assert capsys.readouterr().err == ""
    [row] = setup_rows(open_db)
    assert row.token_hash is None


def test_off_or_demo_never_touches_the_database(settings_env):
    """Checked before the database: a sessionmaker that fails is never called."""

    def broken():
        raise AssertionError("open_setup touched the database")

    settings_env.setenv("SETUP_WIZARD", "false")
    asyncio.run(open_setup(get_settings(), broken))


def test_missing_row_prints_one_line_and_inserts_nothing(open_db, capsys, caplog):
    run(open_db, delete(SetupState))
    caplog.set_level(logging.DEBUG)
    call_open_setup(open_db)
    err = capsys.readouterr().err
    assert "setup record missing" in err
    assert len(err.strip().splitlines()) == 1
    assert "Setup token" not in err
    assert setup_rows(open_db) == []


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


# The lifespan


@pytest.fixture
def migrated_db(tmp_path, settings_env):
    url = f"sqlite+aiosqlite:///{tmp_path / 'migrated.sqlite3'}"
    res = run_alembic(url, "upgrade", "head")
    assert res.returncode == 0, res.stdout + res.stderr
    settings_env.setenv("DATABASE_URL", url)
    settings_env.setenv("SETUP_WIZARD", "true")
    settings_env.setenv("APP_BASE_URL", "http://localhost:3000")
    return url


def start_app() -> None:
    for cached in CACHED:
        cached.cache_clear()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_lifespan_prints_a_new_token_at_each_start(migrated_db, capsys):
    start_app()
    err = capsys.readouterr().err
    first = printed_token(err)
    assert "http://localhost:3000/setup" in err
    start_app()
    second = printed_token(capsys.readouterr().err)
    assert first != second
    [row] = setup_rows(migrated_db)
    assert row.token_hash == hash_token(second)


# require_setup


probe_app = FastAPI()
register_error_handlers(probe_app)


@probe_app.get("/api/setup/probe")
async def probe_route(user: User = Depends(require_setup)) -> dict:
    return {"user": str(user.id)}


@pytest.fixture
def probe(open_db, jwks_cache, capsys):
    """A route behind require_setup, with setup open and two tokens printed."""
    call_open_setup(open_db)
    previous = printed_token(capsys.readouterr().err)
    call_open_setup(open_db)
    current = printed_token(capsys.readouterr().err)
    for cached in CACHED:
        cached.cache_clear()
    probe_app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    try:
        with TestClient(probe_app) as client:
            yield client, previous, current
    finally:
        probe_app.dependency_overrides.clear()


def get_probe(client, headers, token=None):
    if token is not None:
        headers = {**headers, "X-Setup-Token": token}
    return client.get("/api/setup/probe", headers=headers)


def error(response) -> tuple[int, str, str]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["message"]


@pytest.fixture
def spy_compare(monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(setup_state_module.hmac, "compare_digest", spy)
    return calls


def test_current_token_passes(probe, alice, spy_compare):
    client, _previous, current = probe
    response = get_probe(client, alice, current)
    assert response.status_code == 200, response.text
    assert spy_compare == [(hash_token(current), hash_token(current))]


def test_no_header_is_403_not_422(probe, alice):
    client, _previous, _current = probe
    status, code, _message = error(get_probe(client, alice))
    assert (status, code) == (403, "setup_token_invalid")


def test_empty_wrong_and_previous_tokens_get_the_same_403(probe, alice, spy_compare):
    client, previous, _current = probe
    answers = {error(get_probe(client, alice, token)) for token in ("", "wrong-token", previous)}
    answers.add(error(get_probe(client, alice)))
    assert len(answers) == 1
    [(status, code, _message)] = answers
    assert (status, code) == (403, "setup_token_invalid")
    # The wrong and the previous token were compared in constant time.
    assert len(spy_compare) == 2


def test_no_stored_hash_refuses_every_token(probe, alice, open_db, spy_compare):
    client, _previous, current = probe
    run(open_db, update(SetupState).values(token_hash=None))
    for token in (current, "", "anything"):
        status, code, _message = error(get_probe(client, alice, token))
        assert (status, code) == (403, "setup_token_invalid")
    assert spy_compare == []


@pytest.mark.parametrize("close", ["finished", "wizard_off", "row_missing"])
def test_closed_setup_is_404_before_the_token(probe, alice, open_db, settings_env, spy_compare, close):
    client, _previous, current = probe
    if close == "finished":
        run(open_db, update(SetupState).values(completed_at=_now()))
    elif close == "wizard_off":
        settings_env.setenv("SETUP_WIZARD", "false")
        get_settings.cache_clear()
    else:
        run(open_db, delete(SetupState))
    for token in (current, "wrong", None):
        assert error(get_probe(client, alice, token)) == (404, "not_found", "Not found.")
    assert spy_compare == []


def test_no_login_is_401(probe):
    client, _previous, current = probe
    status, code, _message = error(get_probe(client, {}, current))
    assert (status, code) == (401, "unauthenticated")
