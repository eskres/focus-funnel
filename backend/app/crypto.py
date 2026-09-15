"""Encryption for stored secrets (Nebius API keys).

AES-256-GCM with a random 96-bit nonce per write. The owner's user id is the
associated data, so a ciphertext copied onto another user's row fails to
decrypt instead of handing that user someone else's key.
"""

import os
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CURRENT_KEY_VERSION = 1
NONCE_BYTES = 12


class DecryptionError(Exception):
    """The secret can't be decrypted for this user with this master key."""


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    key_version: int


def encrypt_secret(master_key: bytes, user_id: uuid.UUID, plaintext: str) -> EncryptedSecret:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(master_key).encrypt(nonce, plaintext.encode(), user_id.bytes)
    return EncryptedSecret(ciphertext=ciphertext, nonce=nonce, key_version=CURRENT_KEY_VERSION)


def decrypt_secret(master_key: bytes, user_id: uuid.UUID, secret: EncryptedSecret) -> str:
    if secret.key_version != CURRENT_KEY_VERSION:
        raise DecryptionError(f"Unknown key version {secret.key_version}")
    try:
        plaintext = AESGCM(master_key).decrypt(secret.nonce, secret.ciphertext, user_id.bytes)
    except InvalidTag as exc:
        raise DecryptionError("Secret failed authentication") from exc
    return plaintext.decode()
