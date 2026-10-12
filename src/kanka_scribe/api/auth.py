from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from kanka_scribe.auth_util import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from kanka_scribe.config import get_settings
from kanka_scribe.db import get_db
from kanka_scribe.models import User
from kanka_scribe.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if db.query(User).filter_by(email=body.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    is_first = db.query(User).count() == 0
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        is_admin=is_first,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter_by(email=body.email.lower()).first()
    if (
        user is None
        or not user.password_hash
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/oidc/login")
def oidc_login() -> dict:
    settings = get_settings()
    if not settings.oidc_issuer:
        raise HTTPException(status_code=501, detail="OIDC not configured")
    # Discovery-lite: assume standard authorize endpoint under issuer
    authorize = settings.oidc_issuer.rstrip("/") + "/protocol/openid-connect/auth"
    if "googleapis.com" in settings.oidc_issuer or "/.well-known" in settings.oidc_issuer:
        # Prefer well-known when available; keep simple redirect for v1
        authorize = settings.oidc_issuer.rstrip("/") + "/o/oauth2/v2/auth"
    params = urlencode(
        {
            "client_id": settings.oidc_client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": settings.oidc_redirect_uri,
        }
    )
    return {"authorize_url": f"{authorize}?{params}"}


@router.get("/oidc/callback", response_model=TokenResponse)
def oidc_callback(code: str, db: Session = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    if not settings.oidc_issuer:
        raise HTTPException(status_code=501, detail="OIDC not configured")
    token_url = settings.oidc_issuer.rstrip("/") + "/protocol/openid-connect/token"
    with httpx.Client(timeout=30.0) as client:
        token_resp = client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oidc_redirect_uri,
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
            },
        )
        if token_resp.status_code >= 400:
            raise HTTPException(status_code=400, detail="OIDC token exchange failed")
        access = token_resp.json().get("access_token", "")
        userinfo_url = (
            settings.oidc_issuer.rstrip("/") + "/protocol/openid-connect/userinfo"
        )
        info = client.get(
            userinfo_url, headers={"Authorization": f"Bearer {access}"}
        )
        if info.status_code >= 400:
            raise HTTPException(status_code=400, detail="OIDC userinfo failed")
        payload = info.json()
    sub = str(payload.get("sub") or "")
    email = str(payload.get("email") or "").lower()
    if not sub or not email:
        raise HTTPException(status_code=400, detail="OIDC profile incomplete")
    user = db.query(User).filter_by(oidc_sub=sub).first()
    if user is None:
        user = db.query(User).filter_by(email=email).first()
        if user is None:
            user = User(
                email=email,
                oidc_sub=sub,
                is_admin=db.query(User).count() == 0,
            )
            db.add(user)
        else:
            user.oidc_sub = sub
        db.commit()
        db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id))
