from collections.abc import Generator

from sqlalchemy import create_engine, Engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from kanka_scribe.config import get_settings

_engine: Engine | None = None
SessionLocal: sessionmaker | None = None


class Base(DeclarativeBase):
    pass


def get_engine() -> Engine:
    global _engine, SessionLocal
    if _engine is None:
        url = get_settings().database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args)
        SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def reset_engine() -> None:
    """Test helper: drop cached engine so next call re-reads settings."""
    global _engine, SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    SessionLocal = None


def get_db() -> Generator[Session, None, None]:
    get_engine()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_columns(engine: Engine) -> None:
    """Lightweight additive migrations for self-host deploys."""
    additions = [
        ("kanka_campaign_name", "VARCHAR(255) DEFAULT ''"),
        ("kanka_campaign_slug", "VARCHAR(255) DEFAULT ''"),
        ("kanka_public_url", "VARCHAR(500) DEFAULT 'https://kanka.boulware.cloud'"),
        ("discord_webhook_enc", "TEXT DEFAULT ''"),
        ("discord_enabled", "BOOLEAN DEFAULT FALSE"),
        ("discord_username", "VARCHAR(80) DEFAULT 'Goblin Scribe'"),
        ("recap_system_prompt", "TEXT DEFAULT ''"),
        ("entity_type_prompts", "TEXT DEFAULT ''"),
    ]
    url = str(engine.url)
    with engine.begin() as conn:
        if url.startswith("sqlite"):
            cols = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(workspaces)")).fetchall()
            }
            for name, decl in additions:
                if name not in cols:
                    conn.execute(text(f"ALTER TABLE workspaces ADD COLUMN {name} {decl}"))
        else:
            for name, decl in additions:
                conn.execute(
                    text(
                        f"ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS {name} {decl}"
                    )
                )



def init_db() -> None:
    from kanka_scribe import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_columns(engine)
