"""Encrypt workspace secrets at rest."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from kanka_scribe.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.secrets_fernet_key.strip()
    if key:
        return Fernet(key.encode() if isinstance(key, str) else key)
    # Derive a stable key from SECRET_KEY for self-host convenience (document to set Fernet in prod)
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""
