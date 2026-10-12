from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from kanka_scribe.api_keys import authenticate_api_key
from kanka_scribe.config import get_settings
from kanka_scribe.db import get_db
from kanka_scribe.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {"sub": str(user_id), "exp": exp},
        settings.secret_key,
        algorithm="HS256",
    )


def decode_token(token: str) -> int:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc


def _token_from_request(
    request: Request,
    creds: HTTPAuthorizationCredentials | None,
) -> str | None:
    if creds is not None and creds.credentials:
        return creds.credentials
    cookie = request.cookies.get("access_token")
    return cookie or None


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    token = _token_from_request(request, creds)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if token.startswith("ks_"):
        user = authenticate_api_key(db, token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return user
    user_id = decode_token(token)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_optional_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    token = _token_from_request(request, creds)
    if not token:
        return None
    if token.startswith("ks_"):
        return authenticate_api_key(db, token)
    try:
        user_id = decode_token(token)
    except HTTPException:
        return None
    return db.get(User, user_id)
