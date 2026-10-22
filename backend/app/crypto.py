"""Encryption for secrets stored in the database (OAuth tokens, IMAP passwords) and OAuth state.

Fernet gives authenticated encryption (AES-128-CBC with an HMAC), so a value that was
tampered with, or encrypted with another key, fails to decrypt instead of decrypting to
garbage. MultiFernet encrypts with the first key and tries all of them when decrypting,
which allows key rotation: put a new key first, keep the old one until re-encryption.
"""

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import settings


class CryptoError(Exception):
    """A stored secret can't be decrypted (wrong key, or the value was modified)."""


def _fernet() -> MultiFernet:
    keys = settings.encryption_keys
    if not keys:
        # Development fallback: derived from SECRET_KEY, so secrets survive restarts only when
        # SECRET_KEY is set. Production refuses to start without ENCRYPTION_KEY.
        digest = hashlib.sha256(f"mailhub-credentials:{settings.secret_key}".encode()).digest()
        keys = [base64.urlsafe_b64encode(digest).decode()]
    return MultiFernet([Fernet(k) for k in keys])


def encrypt_json(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str, max_age_seconds: int | None = None) -> dict:
    try:
        f = _fernet()
        raw = f.decrypt(token.encode(), ttl=max_age_seconds) if max_age_seconds else f.decrypt(token.encode())
        return json.loads(raw)
    except (InvalidToken, ValueError) as exc:
        raise CryptoError("Could not decrypt the stored value") from exc
