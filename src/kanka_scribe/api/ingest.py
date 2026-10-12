from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from kanka_scribe.api.deps import require_workspace_member
from kanka_scribe.auth_util import get_current_user
from kanka_scribe.connectors.craig import CraigHandoffConnector
from kanka_scribe.db import get_db, get_engine
from kanka_scribe.jobs import run_ingest_job
from kanka_scribe.models import Job, User, Workspace
from kanka_scribe.schemas import HandoffIngestRequest, IngestRequest, JobOut
import kanka_scribe.db as dbmod

router = APIRouter(tags=["ingest"])


def _enqueue(job_id: int) -> None:
    get_engine()
    assert dbmod.SessionLocal is not None
    db = dbmod.SessionLocal()
    try:
        run_ingest_job(db, job_id)
    finally:
        db.close()


def _create_job(
    db: Session,
    workspace_id: int,
    *,
    transcript: str,
    title: str = "",
    recap_markdown: str = "",
    source: str = "manual",
) -> Job:
    job = Job(
        workspace_id=workspace_id,
        status="pending",
        source=source,
        title=title,
        transcript=transcript,
        recap_markdown=recap_markdown,
        result_json="{}",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.post("/ingest", response_model=JobOut)
def ingest_json(
    body: IngestRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Job:
    require_workspace_member(body.workspace_id, user, db)
    if not body.transcript.strip():
        raise HTTPException(status_code=400, detail="transcript required")
    job = _create_job(
        db,
        body.workspace_id,
        transcript=body.transcript,
        title=body.title,
        recap_markdown=body.recap_markdown,
        source=body.source,
    )
    if body.run_sync:
        background.add_task(_enqueue, job.id)
    return job


@router.post("/ingest/upload", response_model=JobOut)
async def ingest_upload(
    background: BackgroundTasks,
    workspace_id: int = Form(...),
    title: str = Form(""),
    recap_markdown: str = Form(""),
    file: UploadFile = File(...),
    run_sync: bool = Form(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Job:
    require_workspace_member(workspace_id, user, db)
    raw = await file.read()
    try:
        transcript = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="file must be UTF-8 text") from exc
    job = _create_job(
        db,
        workspace_id,
        transcript=transcript,
        title=title,
        recap_markdown=recap_markdown,
        source="upload",
    )
    if run_sync:
        background.add_task(_enqueue, job.id)
    return job


@router.post("/ingest/handoff", response_model=list[JobOut])
def ingest_handoff(
    body: HandoffIngestRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Job]:
    ws = require_workspace_member(body.workspace_id, user, db)
    handoff_dir = ws.handoff_dir
    if not handoff_dir:
        raise HTTPException(status_code=400, detail="workspace handoff_dir not set")
    connector = CraigHandoffConnector(handoff_dir)
    jobs: list[Job] = []
    for handoff in connector.list_pending()[: max(1, body.limit)]:
        bundle = connector.fetch(handoff)
        job = _create_job(
            db,
            body.workspace_id,
            transcript=bundle.transcript,
            title=bundle.title,
            recap_markdown=bundle.recap_markdown,
            source="craig",
        )
        connector.mark_ingested(handoff, job.id)
        if body.run_sync:
            background.add_task(_enqueue, job.id)
        jobs.append(job)
    return jobs


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    require_workspace_member(job.workspace_id, user, db)
    return job


@router.get("/workspaces/{workspace_id}/jobs", response_model=list[JobOut])
def list_jobs(
    ws: Workspace = Depends(require_workspace_member),
    db: Session = Depends(get_db),
) -> list[Job]:
    return (
        db.query(Job)
        .filter_by(workspace_id=ws.id)
        .order_by(Job.id.desc())
        .limit(50)
        .all()
    )
