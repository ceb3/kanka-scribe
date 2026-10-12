from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy.orm import Session

from kanka_scribe.models import ApiKey, User


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_api_key(db: Session, user: User, name: str) -> tuple[ApiKey, str]:
    prefix = secrets.token_hex(3)
    secret = secrets.token_urlsafe(32)
    raw = f"ks_{prefix}_{secret}"
    row = ApiKey(
        user_id=user.id,
        name=name.strip() or "default",
        prefix=prefix,
        key_hash=_hash_key(raw),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, raw


def revoke_api_key(db: Session, key: ApiKey) -> None:
    key.revoked_at = datetime.utcnow()
    db.commit()


def authenticate_api_key(db: Session, raw: str) -> User | None:
    if not raw.startswith("ks_") or raw.count("_") < 2:
        return None
    parts = raw.split("_", 2)
    prefix = parts[1]
    row = (
        db.query(ApiKey)
        .filter_by(prefix=prefix, key_hash=_hash_key(raw))
        .first()
    )
    if row is None or row.revoked_at is not None:
        return None
    row.last_used_at = datetime.utcnow()
    db.commit()
    return db.get(User, row.user_id)
