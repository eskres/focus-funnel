"""Encrypted auth values for user connectors.

A connector's bearer token or header value is encrypted like a provider key,
with "connector:<connector id>" as the provider id in the associated data, so
a ciphertext copied onto another connector, or another user's connector,
fails to decrypt. Every value is registered with log masking when it is set
and whenever it is decrypted. Operator connectors store nothing: their value
is read from the environment at call time.
"""

import uuid

from app.crypto import EncryptedSecret, decrypt_secret, encrypt_secret
from app.log_masking import register_secret
from app.models import Connector


def auth_provider_id(connector_id: uuid.UUID) -> str:
    return f"connector:{connector_id}"


def store_auth(master_key: bytes, connector: Connector, value: str | None) -> None:
    """Encrypt value onto the connector's auth columns, or clear them for None.

    The connector's id is part of the associated data, so it is assigned here
    when the row has none yet.
    """
    if not value:
        connector.auth_ciphertext = None
        connector.auth_nonce = None
        connector.auth_key_version = None
        connector.auth_last4 = None
        return
    register_secret(value)
    if connector.id is None:
        connector.id = uuid.uuid4()
    secret = encrypt_secret(
        master_key, connector.user_id, auth_provider_id(connector.id), value
    )
    connector.auth_ciphertext = secret.ciphertext
    connector.auth_nonce = secret.nonce
    connector.auth_key_version = secret.key_version
    connector.auth_last4 = value[-4:]


def read_auth(master_key: bytes, connector: Connector) -> str | None:
    """The connector's decrypted auth value, or None when it stores none.

    Raises DecryptionError when the stored value does not belong to this
    connector and user, or the master key changed.
    """
    if connector.auth_ciphertext is None or connector.auth_nonce is None:
        return None
    secret = EncryptedSecret(
        ciphertext=connector.auth_ciphertext,
        nonce=connector.auth_nonce,
        key_version=connector.auth_key_version or 0,
    )
    value = decrypt_secret(master_key, connector.user_id, auth_provider_id(connector.id), secret)
    register_secret(value)
    return value
