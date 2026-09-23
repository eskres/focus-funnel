import dataclasses
import os
import uuid

import pytest

from app.crypto import DecryptionError, decrypt_secret, encrypt_secret

API_KEY = "nb-test-0123456789abcdef"
PROVIDER_ID = "nebius"


@pytest.fixture
def master_key() -> bytes:
    return os.urandom(32)


def test_round_trip(master_key):
    user_id = uuid.uuid4()
    secret = encrypt_secret(master_key, user_id, PROVIDER_ID, API_KEY)
    assert decrypt_secret(master_key, user_id, PROVIDER_ID, secret) == API_KEY


def test_ciphertext_does_not_contain_plaintext(master_key):
    secret = encrypt_secret(master_key, uuid.uuid4(), PROVIDER_ID, API_KEY)
    assert API_KEY.encode() not in secret.ciphertext


def test_different_user_id_fails_to_decrypt(master_key):
    secret = encrypt_secret(master_key, uuid.uuid4(), PROVIDER_ID, API_KEY)
    with pytest.raises(DecryptionError):
        decrypt_secret(master_key, uuid.uuid4(), PROVIDER_ID, secret)


def test_different_provider_id_fails_to_decrypt(master_key):
    user_id = uuid.uuid4()
    secret = encrypt_secret(master_key, user_id, "nebius", API_KEY)
    with pytest.raises(DecryptionError):
        decrypt_secret(master_key, user_id, "nvidia", secret)


def test_same_key_encrypts_differently_each_time(master_key):
    user_id = uuid.uuid4()
    first = encrypt_secret(master_key, user_id, PROVIDER_ID, API_KEY)
    second = encrypt_secret(master_key, user_id, PROVIDER_ID, API_KEY)
    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext


def test_wrong_master_key_fails(master_key):
    user_id = uuid.uuid4()
    secret = encrypt_secret(master_key, user_id, PROVIDER_ID, API_KEY)
    with pytest.raises(DecryptionError):
        decrypt_secret(os.urandom(32), user_id, PROVIDER_ID, secret)


def test_tampered_ciphertext_fails(master_key):
    user_id = uuid.uuid4()
    secret = encrypt_secret(master_key, user_id, PROVIDER_ID, API_KEY)
    flipped = bytes([secret.ciphertext[0] ^ 1]) + secret.ciphertext[1:]
    with pytest.raises(DecryptionError):
        decrypt_secret(
            master_key, user_id, PROVIDER_ID, dataclasses.replace(secret, ciphertext=flipped)
        )


def test_unknown_key_version_fails(master_key):
    user_id = uuid.uuid4()
    secret = encrypt_secret(master_key, user_id, PROVIDER_ID, API_KEY)
    with pytest.raises(DecryptionError):
        decrypt_secret(master_key, user_id, PROVIDER_ID, dataclasses.replace(secret, key_version=2))
