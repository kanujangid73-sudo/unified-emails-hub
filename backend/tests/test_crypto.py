import time

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.crypto import CryptoError, decrypt_json, encrypt_json


def test_round_trip_and_tamper_detection():
    token = encrypt_json({"password": "s3cret"})
    assert "s3cret" not in token
    assert decrypt_json(token) == {"password": "s3cret"}
    tampered = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]
    with pytest.raises(CryptoError):
        decrypt_json(tampered)


def test_key_rotation(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "encryption_keys", [old])
    sealed = encrypt_json({"v": 1})
    monkeypatch.setattr(settings, "encryption_keys", [new, old])  # new key first, old kept for reading
    assert decrypt_json(sealed) == {"v": 1}
    monkeypatch.setattr(settings, "encryption_keys", [new])
    with pytest.raises(CryptoError):
        decrypt_json(sealed)


def test_max_age(monkeypatch):
    sealed = encrypt_json({"state": 1})
    assert decrypt_json(sealed, max_age_seconds=60) == {"state": 1}
    monkeypatch.setattr(time, "time", lambda: 10**10)  # far in the future
    with pytest.raises(CryptoError):
        decrypt_json(sealed, max_age_seconds=60)


def test_any_long_random_secret_works_as_a_key(monkeypatch):
    # Hosts like Render generate secrets that aren't in Fernet's format.
    monkeypatch.setattr(settings, "encryption_keys", ["J8x2_render-generated-value-that-is-long-enough"])
    sealed = encrypt_json({"ok": True})
    assert decrypt_json(sealed) == {"ok": True}
    monkeypatch.setattr(settings, "encryption_keys", ["a-different-long-random-secret-value-1234"])
    with pytest.raises(CryptoError):
        decrypt_json(sealed)
