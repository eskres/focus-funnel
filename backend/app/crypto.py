"""Encryption for stored secrets (provider API keys).

AES-256-GCM with a random 96-bit nonce per write. The owner's user id and the
provider id are the associated data, so a ciphertext copied onto another
user's row, or onto another provider's row for the same user, fails to
decrypt instead of handing over a key it doesn't belong to.
"""

import os
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CURRENT_KEY_VERSION = 1
NONCE_BYTES = 12


class DecryptionError(Exception):
    """The secret can't be decrypted for this user and provider with this master key."""


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    key_version: int


def _associated_data(user_id: uuid.UUID, provider_id: str) -> bytes:
    return user_id.bytes + b":" + provider_id.encode("utf-8")


def encrypt_secret(
    master_key: bytes, user_id: uuid.UUID, provider_id: str, plaintext: str
) -> EncryptedSecret:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(master_key).encrypt(
        nonce, plaintext.encode(), _associated_data(user_id, provider_id)
    )
    return EncryptedSecret(ciphertext=ciphertext, nonce=nonce, key_version=CURRENT_KEY_VERSION)


def decrypt_secret(
    master_key: bytes, user_id: uuid.UUID, provider_id: str, secret: EncryptedSecret
) -> str:
    if secret.key_version != CURRENT_KEY_VERSION:
        raise DecryptionError(f"Unknown key version {secret.key_version}")
    try:
        plaintext = AESGCM(master_key).decrypt(
            secret.nonce, secret.ciphertext, _associated_data(user_id, provider_id)
        )
    except InvalidTag as exc:
        raise DecryptionError("Secret failed authentication") from exc
    return plaintext.decode()
