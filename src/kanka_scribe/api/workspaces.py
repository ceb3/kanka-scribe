from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from kanka_scribe.api.deps import require_workspace_member
from kanka_scribe.auth_util import get_current_user
from kanka_scribe.db import get_db
from kanka_scribe.kanka_client import probe_campaigns
from kanka_scribe.models import User, Workspace, WorkspaceMember
from kanka_scribe.schemas import (
    ConnectProbeResponse,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from kanka_scribe.prompts import (
    normalize_entity_type_prompts,
    normalize_recap_system_prompt,
    parse_entity_type_prompts,
)
from kanka_scribe.secrets import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _to_out(ws: Workspace) -> WorkspaceOut:
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        kanka_base_url=ws.kanka_base_url,
        kanka_api_prefix=ws.kanka_api_prefix,
        kanka_campaign_id=ws.kanka_campaign_id,
        kanka_campaign_name=ws.kanka_campaign_name or "",
        kanka_campaign_slug=ws.kanka_campaign_slug or "",
        kanka_profile=ws.kanka_profile,
        kanka_token_set=bool(ws.kanka_token_enc),
        llm_base_url=ws.llm_base_url,
        llm_api_key_set=bool(ws.llm_api_key_enc),
        llm_model=ws.llm_model,
        llm_context_length=ws.llm_context_length,
        handoff_dir=ws.handoff_dir,
        kanka_public_url=ws.kanka_public_url or "https://kanka.boulware.cloud",
        discord_webhook_set=bool(ws.discord_webhook_enc),
        discord_enabled=bool(ws.discord_enabled),
        discord_username=ws.discord_username or "Goblin Scribe",
        recap_system_prompt=ws.recap_system_prompt or "",
        entity_type_prompts=parse_entity_type_prompts(ws.entity_type_prompts),
    )


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[WorkspaceOut]:
    if user.is_admin:
        rows = db.query(Workspace).order_by(Workspace.id).all()
    else:
        rows = (
            db.query(Workspace)
            .join(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id)
            .order_by(Workspace.id)
            .all()
        )
    return [_to_out(ws) for ws in rows]


@router.post("", response_model=WorkspaceOut)
def create_workspace(
    body: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    ws = Workspace(
        name=body.name,
        kanka_base_url=body.kanka_base_url,
        kanka_api_prefix=body.kanka_api_prefix or "/1.0",
        kanka_campaign_id=body.kanka_campaign_id,
        kanka_campaign_name=body.kanka_campaign_name or "",
        kanka_campaign_slug=body.kanka_campaign_slug or "",
        kanka_token_enc=encrypt_secret(body.kanka_token) if body.kanka_token else "",
        kanka_profile=body.kanka_profile or "ce",
        llm_base_url=body.llm_base_url,
        llm_api_key_enc=encrypt_secret(body.llm_api_key) if body.llm_api_key else "",
        llm_model=body.llm_model,
        llm_context_length=body.llm_context_length,
        handoff_dir=body.handoff_dir,
        kanka_public_url=body.kanka_public_url
        or "https://kanka.boulware.cloud",
        discord_webhook_enc=encrypt_secret(body.discord_webhook)
        if body.discord_webhook
        else "",
        discord_enabled=body.discord_enabled,
        discord_username=body.discord_username or "Goblin Scribe",
        recap_system_prompt=normalize_recap_system_prompt(
            body.recap_system_prompt
        ),
        entity_type_prompts=normalize_entity_type_prompts(
            body.entity_type_prompts
        ),
    )
    db.add(ws)
    db.flush()
    db.add(
        WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="admin")
    )
    db.commit()
    db.refresh(ws)
    return _to_out(ws)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(
    ws: Workspace = Depends(require_workspace_member),
) -> WorkspaceOut:
    return _to_out(ws)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    body: WorkspaceUpdate,
    ws: Workspace = Depends(require_workspace_member),
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    data = body.model_dump(exclude_unset=True)
    token = data.pop("kanka_token", None)
    llm_key = data.pop("llm_api_key", None)
    discord_hook = data.pop("discord_webhook", None)
    if "recap_system_prompt" in data:
        data["recap_system_prompt"] = normalize_recap_system_prompt(
            data["recap_system_prompt"]
        )
    if "entity_type_prompts" in data:
        data["entity_type_prompts"] = normalize_entity_type_prompts(
            data["entity_type_prompts"]
        )
    for key, value in data.items():
        setattr(ws, key, value)
    if token is not None:
        ws.kanka_token_enc = encrypt_secret(token) if token else ""
    if llm_key is not None:
        ws.llm_api_key_enc = encrypt_secret(llm_key) if llm_key else ""
    if discord_hook is not None:
        ws.discord_webhook_enc = encrypt_secret(discord_hook) if discord_hook else ""
    db.commit()
    db.refresh(ws)
    return _to_out(ws)


@router.post("/{workspace_id}/probe", response_model=ConnectProbeResponse)
def probe_workspace(
    ws: Workspace = Depends(require_workspace_member),
) -> ConnectProbeResponse:
    token = decrypt_secret(ws.kanka_token_enc)
    if not ws.kanka_base_url or not token:
        raise HTTPException(status_code=400, detail="Kanka URL/token not set")
    try:
        campaigns = probe_campaigns(
            ws.kanka_base_url, token, api_prefix=ws.kanka_api_prefix or "/1.0"
        )
    except Exception as exc:
        return ConnectProbeResponse(
            ok=False, profile=ws.kanka_profile, campaigns=[], message=str(exc)
        )
    profile = "saas" if "kanka.io" in ws.kanka_base_url.lower() else ws.kanka_profile
    return ConnectProbeResponse(
        ok=True, profile=profile, campaigns=campaigns, message="ok"
    )
