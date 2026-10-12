from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    is_admin: bool

    model_config = {"from_attributes": True}


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kanka_base_url: str = ""
    kanka_api_prefix: str = "/1.0"
    kanka_campaign_id: int | None = None
    kanka_campaign_name: str = ""
    kanka_campaign_slug: str = ""
    kanka_token: str = ""
    kanka_profile: str = "ce"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_context_length: int = 32768
    handoff_dir: str = ""
    kanka_public_url: str = ""
    discord_webhook: str = ""
    discord_enabled: bool = False
    discord_username: str = "Goblin Scribe"
    recap_system_prompt: str = ""
    entity_type_prompts: dict[str, str] = {}


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    kanka_base_url: str | None = None
    kanka_api_prefix: str | None = None
    kanka_campaign_id: int | None = None
    kanka_campaign_name: str | None = None
    kanka_campaign_slug: str | None = None
    kanka_token: str | None = None
    kanka_profile: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_context_length: int | None = None
    handoff_dir: str | None = None
    kanka_public_url: str | None = None
    discord_webhook: str | None = None
    discord_enabled: bool | None = None
    discord_username: str | None = None
    recap_system_prompt: str | None = None
    entity_type_prompts: dict[str, str] | None = None


class WorkspaceOut(BaseModel):
    id: int
    name: str
    kanka_base_url: str
    kanka_api_prefix: str
    kanka_campaign_id: int | None
    kanka_campaign_name: str
    kanka_campaign_slug: str
    kanka_profile: str
    kanka_token_set: bool
    llm_base_url: str
    llm_api_key_set: bool
    llm_model: str
    llm_context_length: int
    handoff_dir: str
    kanka_public_url: str
    discord_webhook_set: bool
    discord_enabled: bool
    discord_username: str
    recap_system_prompt: str
    entity_type_prompts: dict[str, str]


class IngestRequest(BaseModel):
    workspace_id: int
    transcript: str
    title: str = ""
    recap_markdown: str = ""
    source: str = "manual"
    run_sync: bool = True


class JobOut(BaseModel):
    id: int
    workspace_id: int
    status: str
    source: str
    title: str
    recap_markdown: str
    result_json: str
    error: str

    model_config = {"from_attributes": True}


class HandoffIngestRequest(BaseModel):
    workspace_id: int
    run_sync: bool = True
    limit: int = 10


class ConnectProbeResponse(BaseModel):
    ok: bool
    profile: str
    campaigns: list[dict]
    message: str = ""
