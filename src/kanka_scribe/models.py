from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kanka_scribe.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oidc_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    memberships: Mapped[list[WorkspaceMember]] = relationship(back_populates="user")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kanka_base_url: Mapped[str] = mapped_column(String(500), default="")
    kanka_api_prefix: Mapped[str] = mapped_column(String(32), default="/1.0")
    kanka_campaign_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kanka_campaign_name: Mapped[str] = mapped_column(String(255), default="")
    kanka_campaign_slug: Mapped[str] = mapped_column(String(255), default="")
    kanka_token_enc: Mapped[str] = mapped_column(Text, default="")
    kanka_profile: Mapped[str] = mapped_column(String(16), default="ce")
    llm_base_url: Mapped[str] = mapped_column(String(500), default="")
    llm_api_key_enc: Mapped[str] = mapped_column(Text, default="")
    llm_model: Mapped[str] = mapped_column(String(120), default="")
    llm_context_length: Mapped[int] = mapped_column(Integer, default=32768)
    handoff_dir: Mapped[str] = mapped_column(String(500), default="")
    # Public Kanka UI base for Discord links (may differ from API base URL)
    kanka_public_url: Mapped[str] = mapped_column(String(500), default="")
    discord_webhook_enc: Mapped[str] = mapped_column(Text, default="")
    discord_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    discord_username: Mapped[str] = mapped_column(String(80), default="Goblin Scribe")
    # Empty → use built-in Goblin Scribe Session Overview prompt from prompts.SYSTEM
    recap_system_prompt: Mapped[str] = mapped_column(Text, default="")
    # JSON object of per-type detail-field prompt overrides (empty → built-ins)
    entity_type_prompts: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    members: Mapped[list[WorkspaceMember]] = relationship(back_populates="workspace")
    jobs: Mapped[list[Job]] = relationship(back_populates="workspace")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(32), default="member")

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    source: Mapped[str] = mapped_column(String(64), default="manual")
    title: Mapped[str] = mapped_column(String(255), default="")
    transcript: Mapped[str] = mapped_column(Text, default="")
    recap_markdown: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    workspace: Mapped[Workspace] = relationship(back_populates="jobs")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120), default="")
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="api_keys")


class AppLog(Base):
    __tablename__ = "app_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
