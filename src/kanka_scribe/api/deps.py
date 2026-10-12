from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from kanka_scribe.auth_util import get_current_user
from kanka_scribe.db import get_db
from kanka_scribe.models import User, Workspace, WorkspaceMember


def require_workspace_member(
    workspace_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if user.is_admin:
        return ws
    membership = (
        db.query(WorkspaceMember)
        .filter_by(workspace_id=workspace_id, user_id=user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    return ws
