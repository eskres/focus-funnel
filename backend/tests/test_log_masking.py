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
    headers = {"Authorization": f"Bearer {make_token(sub='auth0|logs')}"}

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
    headers = {"Authorization": f"Bearer {make_token(sub='auth0|logs')}"}
    with caplog.at_level(logging.DEBUG):
        client.put(
            "/api/providers/nebius/key", headers=headers, json={"key": 12345, "extra": SECRET}
        )
    assert SECRET not in caplog.text
