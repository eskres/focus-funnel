import contextvars
import logging

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.auth import get_jwks_cache
from app.log_masking import MASK, install_log_masking, register_secret
from app.main import app
from app.providers import get_provider_http_client
from tests.conftest import FakeProvider, fail_with, status

SECRET = "nb-super-secret-key-9f8e7d6c"
logger = logging.getLogger("tests.log_masking")


def in_fresh_context(fn):
    """Run fn in a copied context so registered secrets don't leak between tests."""
    return contextvars.copy_context().run(fn)


@pytest.fixture(autouse=True)
def masking_installed():
    install_log_masking()


def test_message_and_args_are_masked(caplog):
    def run():
        register_secret(SECRET)
        with caplog.at_level(logging.INFO):
            logger.info("saving key %s for user", SECRET)
            logger.info(f"inline {SECRET}")

    in_fresh_context(run)
    assert SECRET not in caplog.text
    assert caplog.text.count(MASK) == 2


def test_exception_traceback_is_masked(caplog):
    def run():
        register_secret(SECRET)
        with caplog.at_level(logging.ERROR):
            try:
                raise RuntimeError(f"request failed with key {SECRET}")
            except RuntimeError:
                logger.exception("boom")

    in_fresh_context(run)
    assert SECRET not in caplog.text
    assert MASK in caplog.text


def test_short_values_are_not_masked(caplog):
    def run():
        register_secret("abc")
        with caplog.at_level(logging.INFO):
            logger.info("abc stays readable")

    in_fresh_context(run)
    assert "abc stays readable" in caplog.text


def test_secret_from_one_context_is_not_masked_in_another(caplog):
    in_fresh_context(lambda: register_secret(SECRET))

    def run():
        with caplog.at_level(logging.INFO):
            logger.info("unrelated %s", SECRET)

    in_fresh_context(run)
    assert SECRET in caplog.text


def test_install_is_idempotent():
    install_log_masking()
    factory = logging.getLogRecordFactory()
    install_log_masking()
    assert logging.getLogRecordFactory() is factory


# --- saving a key through the API with every logger at DEBUG ---


@pytest.fixture
def client(test_database_url, jwks_cache, settings_env):
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "respond",
    [
        status(200, {"object": "list", "data": []}),
        status(401),
        status(503),
        fail_with(httpx2.ConnectError),
    ],
    ids=["valid", "invalid", "server-error", "connection-error"],
)
def test_key_never_appears_in_logs_during_save(client, make_token, caplog, respond):
    fake = FakeProvider(respond)
    app.dependency_overrides[get_provider_http_client] = lambda: fake.http_client()
    headers = {"Authorization": f"Bearer {make_token(sub='user|logs')}"}

    with caplog.at_level(logging.DEBUG):
        client.put("/api/providers/nebius/key", headers=headers, json={"key": SECRET})
        client.get("/api/providers", headers=headers)

    assert fake.requests, "the save must have reached the fake provider API"
    assert caplog.records, "DEBUG logging should capture SDK and app records"
    for record in caplog.records:
        assert SECRET not in record.getMessage()
        assert SECRET not in (record.exc_text or "")
    assert SECRET not in caplog.text


def test_key_never_appears_in_logs_on_validation_failure(client, make_token, caplog):
    headers = {"Authorization": f"Bearer {make_token(sub='user|logs')}"}
    with caplog.at_level(logging.DEBUG):
        client.put(
            "/api/providers/nebius/key", headers=headers, json={"key": 12345, "extra": SECRET}
        )
    assert SECRET not in caplog.text


# ------------------------------------------------------------ access log queries
# thought-library task 1.3: a filter value is the user's own words, so the
# query string never reaches the access log (design decision 4).


ACCESS_ARGS = ("127.0.0.1:50000", "GET", "/", "1.1", 200)


def access_formatter() -> logging.Formatter:
    from uvicorn.config import LOGGING_CONFIG
    from uvicorn.logging import AccessFormatter

    return AccessFormatter(fmt=LOGGING_CONFIG["formatters"]["access"]["fmt"], use_colors=False)


def access_args(path: str) -> tuple:
    return (ACCESS_ARGS[0], ACCESS_ARGS[1], path, ACCESS_ARGS[3], ACCESS_ARGS[4])


def access_line(path: str) -> tuple[str, logging.LogRecord]:
    """An access record as uvicorn makes it, through the record factory,
    formatted as uvicorn formats it."""
    access = logging.getLogger("uvicorn.access")
    record = access.makeRecord(
        access.name, logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d', access_args(path), None
    )
    return access_formatter().format(record), record


def unmasked_line(path: str) -> str:
    """The same record made without the factory, as uvicorn would log it unmasked."""
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d', access_args(path), None
    )
    return access_formatter().format(record)


def test_the_access_log_drops_the_query_string():
    line, record = access_line("/api/thoughts?tag=therapy&category=health")
    assert '"GET /api/thoughts HTTP/1.1" 200' in line
    assert "therapy" not in line
    assert "health" not in line
    assert line == unmasked_line("/api/thoughts")
    assert isinstance(record.args, tuple)
    assert len(record.args) == 5


def test_the_query_is_dropped_with_a_secret_registered():
    def run():
        register_secret(SECRET)
        return access_line("/api/thoughts?tag=therapy&category=health")

    line, record = in_fresh_context(run)
    assert '"GET /api/thoughts HTTP/1.1" 200' in line
    assert "therapy" not in line
    assert "health" not in line
    assert len(record.args) == 5


def test_a_path_with_no_query_is_logged_as_before():
    line, record = access_line("/api/thoughts/upcoming")
    assert line == unmasked_line("/api/thoughts/upcoming")
    assert '"GET /api/thoughts/upcoming HTTP/1.1" 200' in line
    assert record.args == ("127.0.0.1:50000", "GET", "/api/thoughts/upcoming", "1.1", 200)


def test_other_loggers_keep_their_question_marks(caplog):
    with caplog.at_level(logging.INFO):
        logger.info("%s %s %s %s %s", "a", "b", "/path?keep=1", "d", "e")
    assert "/path?keep=1" in caplog.text
