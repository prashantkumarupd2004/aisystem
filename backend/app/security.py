"""Password hashing, JWT and at-rest token encryption.

Instagram / Google tokens are NEVER stored in plain text and NEVER
returned by any API response. Only the encrypted blob is persisted.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from jose import jwt

from .config import settings

log = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = settings.token_encryption_key
    if key:
        try:
            _fernet = Fernet(key.encode())
            return _fernet
        except Exception:
            log.error("TOKEN_ENCRYPTION_KEY is not a valid Fernet key.")
            raise
    # Dev-only fallback: ephemeral key, tokens do not survive restart.
    if settings.environment == "production":
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required in production")
    log.warning(
        "TOKEN_ENCRYPTION_KEY not set: using an ephemeral key. "
        "Encrypted tokens will NOT survive a restart. Set the key in .env."
    )
    _fernet = Fernet(Fernet.generate_key())
    return _fernet


def reset_fernet_cache() -> None:
    global _fernet
    _fernet = None


def encrypt_token(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_token(blob: str) -> str:
    try:
        return _get_fernet().decrypt(blob.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("stored token cannot be decrypted with current key") from exc


def hash_password(password: str) -> str:
    # bcrypt itself caps at 72 bytes; fail loudly instead of silently
    # truncating a password (passlib's old behaviour hid this).
    data = password.encode()
    if len(data) > 72:
        raise ValueError("Password must be 72 bytes or shorter")
    return bcrypt.hashpw(data, bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode(
        {"sub": subject, "role": role, "exp": expire},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
