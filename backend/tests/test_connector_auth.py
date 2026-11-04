"""Connector auth encryption (mcp-connectors task 3.2)."""

import contextvars
import logging
import os
import uuid

import pytest

from app.connector_auth import auth_provider_id, read_auth, store_auth
from app.crypto import DecryptionError
from app.log_masking import MASK, install_log_masking
from app.models import Connector

TOKEN = "gcal-bearer-0123456789abcdef"
logger = logging.getLogger("tests.connector_auth")


@pytest.fixture
def master_key() -> bytes:
    return os.urandom(32)


def connector(user_id: uuid.UUID | None = None) -> Connector:
    return Connector(
        id=uuid.uuid4(), user_id=user_id or uuid.uuid4(), name="calendar", source="user", auth_kind="bearer"
    )


def move_auth(source: Connector, target: Connector) -> None:
    target.auth_ciphertext = source.auth_ciphertext
    target.auth_nonce = source.auth_nonce
    target.auth_key_version = source.auth_key_version


def in_fresh_context(fn):
    """Run fn in a copied context so registered secrets don't leak between tests."""
    return contextvars.copy_context().run(fn)


def test_round_trip_keeps_last4_and_never_the_value(master_key):
    row = connector()
    in_fresh_context(lambda: store_auth(master_key, row, TOKEN))
    assert row.auth_last4 == "cdef"
    assert TOKEN.encode() not in row.auth_ciphertext
    assert in_fresh_context(lambda: read_auth(master_key, row)) == TOKEN


def test_store_assigns_an_id_first_and_none_clears(master_key):
    row = Connector(user_id=uuid.uuid4(), name="calendar", source="user", auth_kind="bearer")
    in_fresh_context(lambda: store_auth(master_key, row, TOKEN))
    assert row.id is not None
    assert read_auth(master_key, row) == TOKEN

    store_auth(master_key, row, None)
    assert (row.auth_ciphertext, row.auth_nonce, row.auth_key_version, row.auth_last4) == (None,) * 4
    assert read_auth(master_key, row) is None


def test_provider_id_names_the_connector():
    connector_id = uuid.uuid4()
    assert auth_provider_id(connector_id) == f"connector:{connector_id}"


def test_ciphertext_moved_to_another_connector_fails(master_key):
    source = connector()
    in_fresh_context(lambda: store_auth(master_key, source, TOKEN))
    other = connector(source.user_id)
    move_auth(source, other)
    with pytest.raises(DecryptionError):
        read_auth(master_key, other)


def test_ciphertext_moved_to_another_user_fails(master_key):
    source = connector()
    in_fresh_context(lambda: store_auth(master_key, source, TOKEN))
    # Same connector id, another owner.
    other = connector()
    other.id = source.id
    move_auth(source, other)
    with pytest.raises(DecryptionError):
        read_auth(master_key, other)


def test_decrypted_value_is_masked_in_logs(master_key, caplog):
    install_log_masking()
    row = connector()
    # Stored in one request, decrypted in a later one.
    in_fresh_context(lambda: store_auth(master_key, row, TOKEN))

    def later_request():
        value = read_auth(master_key, row)
        with caplog.at_level(logging.INFO):
            logger.info("calling the server with %s", value)

    in_fresh_context(later_request)
    assert TOKEN not in caplog.text
    assert MASK in caplog.text
