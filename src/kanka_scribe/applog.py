from __future__ import annotations

from sqlalchemy.orm import Session

from kanka_scribe.models import AppLog


def write_log(
    db: Session,
    message: str,
    *,
    level: str = "info",
    workspace_id: int | None = None,
    job_id: int | None = None,
    user_id: int | None = None,
    commit: bool = True,
) -> AppLog:
    row = AppLog(
        level=level,
        message=message,
        workspace_id=workspace_id,
        job_id=job_id,
        user_id=user_id,
    )
    db.add(row)
    if commit:
        db.commit()
    else:
        db.flush()
    return row
