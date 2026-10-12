from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from kanka_scribe.api import auth, ingest, workspaces
from kanka_scribe.api.deps import require_workspace_member
from kanka_scribe.api.ingest import _create_job, _enqueue
from kanka_scribe.api_keys import create_api_key, revoke_api_key
from kanka_scribe.applog import write_log
from kanka_scribe.auth_util import (
    create_access_token,
    get_current_user,
    get_optional_user,
    hash_password,
    verify_password,
)
from kanka_scribe.config import default_kanka_public_url, get_settings
from kanka_scribe.db import get_db, init_db
from kanka_scribe.kanka_campaign import apply_campaign_record, find_campaign
from kanka_scribe.kanka_client import probe_campaigns
from kanka_scribe.models import ApiKey, AppLog, Job, User, Workspace, WorkspaceMember
from kanka_scribe.prompts import (
    ENTITY_TYPE_LABELS,
    ENTITY_TYPE_PROMPT_KEYS,
    SYSTEM,
    normalize_entity_type_prompts,
    normalize_recap_system_prompt,
    parse_entity_type_prompts,
    resolve_entity_type_prompts,
)
from kanka_scribe.secrets import decrypt_secret, encrypt_secret

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def _user_workspaces(db: Session, user: User) -> list[Workspace]:
    if user.is_admin:
        return db.query(Workspace).order_by(Workspace.id).all()
    return (
        db.query(Workspace)
        .join(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.id)
        .all()
    )


def _flash(request: Request) -> tuple[str, str]:
    return (
        request.query_params.get("flash", ""),
        request.query_params.get("kind", "ok"),
    )


def _ctx(
    request: Request,
    *,
    user: User,
    nav: str,
    app_name: str,
    flash: str | None = None,
    flash_kind: str | None = None,
    **extra,
) -> dict:
    q_flash, q_kind = _flash(request)
    return {
        "request": request,
        "app_name": app_name,
        "user": user,
        "nav": nav,
        "flash": flash if flash is not None else q_flash,
        "flash_kind": flash_kind if flash_kind is not None else q_kind,
        **extra,
    }


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        db = next(get_db())
        try:
            if db.query(User).count() == 0 and settings.bootstrap_admin_email:
                db.add(
                    User(
                        email=settings.bootstrap_admin_email.lower(),
                        password_hash=hash_password(
                            settings.bootstrap_admin_password
                        ),
                        is_admin=True,
                    )
                )
                db.commit()
        finally:
            db.close()
        yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(workspaces.router, prefix="/api/v1")
    app.include_router(ingest.router, prefix="/api/v1")

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        if exc.status_code == 401 and request.url.path.startswith("/ui/"):
            return RedirectResponse("/", status_code=303)
        return await http_exception_handler(request, exc)

    static_dir = PACKAGE_DIR / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/", response_model=None)
    def home(
        request: Request,
        user: User | None = Depends(get_optional_user),
    ):
        if user is not None:
            return RedirectResponse("/ui/app", status_code=303)
        flash, kind = _flash(request)
        if request.query_params.get("error") == "auth":
            flash, kind = "Invalid email or password.", "err"
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "app_name": settings.app_name,
                "user": None,
                "flash": flash,
                "flash_kind": kind,
            },
        )

    @app.post("/ui/login")
    def ui_login(
        email: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        user = db.query(User).filter_by(email=email.lower()).first()
        if (
            user is None
            or not user.password_hash
            or not verify_password(password, user.password_hash)
        ):
            return RedirectResponse("/?error=auth", status_code=303)
        token = create_access_token(user.id)
        write_log(db, f"User signed in: {user.email}", user_id=user.id)
        resp = RedirectResponse("/ui/app", status_code=303)
        resp.set_cookie(
            "access_token",
            token,
            httponly=True,
            samesite="lax",
            max_age=settings.jwt_expire_minutes * 60,
        )
        return resp

    @app.get("/ui/logout")
    def ui_logout() -> RedirectResponse:
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie("access_token")
        return resp

    @app.get("/ui/app", response_model=None)
    def ui_ingest(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        ws_list = _user_workspaces(db, user)
        jobs: list[Job] = []
        if ws_list:
            ws_ids = [w.id for w in ws_list]
            jobs = (
                db.query(Job)
                .filter(Job.workspace_id.in_(ws_ids))
                .order_by(Job.id.desc())
                .limit(8)
                .all()
            )
        selected = request.query_params.get("workspace_id")
        selected_id = int(selected) if selected and selected.isdigit() else None
        return templates.TemplateResponse(
            request,
            "ingest.html",
            _ctx(
                request,
                user=user,
                nav="ingest",
                app_name=settings.app_name,
                workspaces=ws_list,
                jobs=jobs,
                selected_workspace_id=selected_id,
            ),
        )

    @app.post("/ui/ingest")
    async def ui_ingest_post(
        background: BackgroundTasks,
        workspace_id: int = Form(...),
        title: str = Form(""),
        recap_markdown: str = Form(""),
        transcript: str = Form(""),
        run_sync: str | None = Form(None),
        file: UploadFile | None = File(None),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        require_workspace_member(workspace_id, user, db)
        text = (transcript or "").strip()
        source = "paste"
        if file is not None and file.filename:
            raw = await file.read()
            try:
                text = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                return RedirectResponse(
                    "/ui/app?flash="
                    + quote("File must be UTF-8 text")
                    + "&kind=err",
                    status_code=303,
                )
            source = "upload"
        if not text:
            return RedirectResponse(
                "/ui/app?flash="
                + quote("Provide a file or paste a transcript")
                + "&kind=err",
                status_code=303,
            )
        job = _create_job(
            db,
            workspace_id,
            transcript=text,
            title=title.strip(),
            recap_markdown=recap_markdown.strip(),
            source=source,
        )
        write_log(
            db,
            f"Ingest queued via UI ({source})",
            workspace_id=workspace_id,
            job_id=job.id,
            user_id=user.id,
        )
        if run_sync:
            background.add_task(_enqueue, job.id)
        return RedirectResponse(f"/ui/jobs/{job.id}", status_code=303)

    @app.get("/ui/jobs", response_model=None)
    def ui_jobs(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        ws_list = _user_workspaces(db, user)
        ws_ids = [w.id for w in ws_list]
        jobs = (
            db.query(Job)
            .filter(Job.workspace_id.in_(ws_ids))
            .order_by(Job.id.desc())
            .limit(100)
            .all()
            if ws_ids
            else []
        )
        names = {w.id: w.name for w in ws_list}
        return templates.TemplateResponse(
            request,
            "jobs.html",
            _ctx(
                request,
                user=user,
                nav="jobs",
                app_name=settings.app_name,
                jobs=jobs,
                workspace_names=names,
            ),
        )

    @app.get("/ui/jobs/{job_id}", response_model=None)
    def ui_job(
        job_id: int,
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        job = db.get(Job, job_id)
        if job is None:
            return RedirectResponse(
                "/ui/jobs?flash=" + quote("Job not found") + "&kind=err",
                status_code=303,
            )
        require_workspace_member(job.workspace_id, user, db)
        result = None
        if job.result_json:
            try:
                result = json.loads(job.result_json)
            except json.JSONDecodeError:
                result = None
        job_logs = (
            db.query(AppLog)
            .filter_by(job_id=job.id)
            .order_by(AppLog.id.desc())
            .limit(50)
            .all()
        )
        return templates.TemplateResponse(
            request,
            "job.html",
            _ctx(
                request,
                user=user,
                nav="jobs",
                app_name=settings.app_name,
                job=job,
                result=result,
                job_logs=list(reversed(job_logs)),
            ),
        )

    @app.get("/ui/settings", response_model=None)
    def ui_settings(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        ws_list = _user_workspaces(db, user)
        create_new = request.query_params.get("new") == "1"
        selected = request.query_params.get("workspace_id")
        workspace = None
        if not create_new:
            if selected and selected.isdigit():
                workspace = next(
                    (w for w in ws_list if w.id == int(selected)), None
                )
            elif ws_list:
                workspace = ws_list[0]

        campaigns: list[dict] = []
        if request.query_params.get("probed") == "1" and workspace:
            token = decrypt_secret(workspace.kanka_token_enc)
            if workspace.kanka_base_url and token:
                try:
                    campaigns = probe_campaigns(
                        workspace.kanka_base_url,
                        token,
                        api_prefix=workspace.kanka_api_prefix or "/1.0",
                    )
                except Exception:
                    campaigns = []

        recap_prompt = (
            (workspace.recap_system_prompt or "").strip() if workspace else ""
        ) or SYSTEM
        stored_entity = (
            workspace.entity_type_prompts if workspace else ""
        )
        return templates.TemplateResponse(
            request,
            "settings.html",
            _ctx(
                request,
                user=user,
                nav="settings",
                app_name=settings.app_name,
                workspace=workspace,
                workspaces=ws_list,
                campaigns=campaigns,
                recap_system_prompt=recap_prompt,
                entity_type_prompt_keys=ENTITY_TYPE_PROMPT_KEYS,
                entity_type_labels=ENTITY_TYPE_LABELS,
                entity_type_prompts=resolve_entity_type_prompts(stored_entity),
                entity_type_overrides=set(parse_entity_type_prompts(stored_entity)),
                default_kanka_public_url=settings.default_kanka_public_url,
                default_llm_base_url_placeholder=settings.default_llm_base_url_placeholder,
            ),
        )

    @app.post("/ui/settings")
    def ui_settings_post(
        action: str = Form("save"),
        workspace_id: int | None = Form(None),
        name: str = Form(...),
        kanka_base_url: str = Form(""),
        kanka_api_prefix: str = Form("/1.0"),
        kanka_profile: str = Form("ce"),
        kanka_token: str = Form(""),
        kanka_campaign_id: str = Form(""),
        llm_base_url: str = Form(""),
        llm_model: str = Form(""),
        llm_context_length: int = Form(32768),
        llm_api_key: str = Form(""),
        handoff_dir: str = Form(""),
        kanka_public_url: str = Form(""),
        discord_enabled: str | None = Form(None),
        discord_webhook: str = Form(""),
        discord_username: str = Form("Goblin Scribe"),
        recap_system_prompt: str = Form(""),
        entity_prompt_character: str = Form(""),
        entity_prompt_location: str = Form(""),
        entity_prompt_organisation: str = Form(""),
        entity_prompt_creature: str = Form(""),
        entity_prompt_quest: str = Form(""),
        entity_prompt_item: str = Form(""),
        entity_prompt_event: str = Form(""),
        entity_prompt_other: str = Form(""),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        campaign_id = (
            int(kanka_campaign_id) if kanka_campaign_id.strip().isdigit() else None
        )
        ws: Workspace | None = None
        if workspace_id:
            ws = require_workspace_member(workspace_id, user, db)
        else:
            ws = Workspace(name=name.strip() or "Home")
            db.add(ws)
            db.flush()
            db.add(
                WorkspaceMember(
                    workspace_id=ws.id, user_id=user.id, role="admin"
                )
            )

        ws.name = name.strip() or ws.name
        ws.kanka_base_url = kanka_base_url.strip()
        ws.kanka_api_prefix = kanka_api_prefix.strip() or "/1.0"
        ws.kanka_profile = kanka_profile if kanka_profile in {"ce", "saas"} else "ce"
        if kanka_token.strip():
            ws.kanka_token_enc = encrypt_secret(kanka_token.strip())
        ws.llm_base_url = llm_base_url.strip()
        ws.llm_model = llm_model.strip()
        ws.llm_context_length = llm_context_length or 32768
        if llm_api_key.strip():
            ws.llm_api_key_enc = encrypt_secret(llm_api_key.strip())
        ws.handoff_dir = handoff_dir.strip()
        ws.kanka_public_url = (
            kanka_public_url.strip() or default_kanka_public_url()
        )
        ws.discord_enabled = bool(discord_enabled)
        ws.discord_username = discord_username.strip() or "Goblin Scribe"
        if discord_webhook.strip():
            ws.discord_webhook_enc = encrypt_secret(discord_webhook.strip())
        ws.recap_system_prompt = normalize_recap_system_prompt(recap_system_prompt)
        ws.entity_type_prompts = normalize_entity_type_prompts(
            {
                "character": entity_prompt_character,
                "location": entity_prompt_location,
                "organisation": entity_prompt_organisation,
                "creature": entity_prompt_creature,
                "quest": entity_prompt_quest,
                "item": entity_prompt_item,
                "event": entity_prompt_event,
                "other": entity_prompt_other,
            }
        )

        if action == "probe":
            token = decrypt_secret(ws.kanka_token_enc)
            if not ws.kanka_base_url or not token:
                db.commit()
                return RedirectResponse(
                    f"/ui/settings?workspace_id={ws.id}&flash="
                    + quote("Set Kanka URL and PAT before probing")
                    + "&kind=err",
                    status_code=303,
                )
            try:
                campaigns = probe_campaigns(
                    ws.kanka_base_url,
                    token,
                    api_prefix=ws.kanka_api_prefix or "/1.0",
                )
            except Exception as exc:
                db.commit()
                write_log(
                    db,
                    f"Kanka probe failed: {exc}",
                    level="error",
                    workspace_id=ws.id,
                    user_id=user.id,
                )
                return RedirectResponse(
                    f"/ui/settings?workspace_id={ws.id}&flash="
                    + quote(f"Probe failed: {exc}")
                    + "&kind=err",
                    status_code=303,
                )
            if "kanka.io" in ws.kanka_base_url.lower():
                ws.kanka_profile = "saas"
            # keep selected campaign if still present; else set from form
            ws.kanka_campaign_id = campaign_id
            match = find_campaign(campaigns, campaign_id)
            apply_campaign_record(ws, match)
            db.commit()
            write_log(
                db,
                f"Kanka probe ok — {len(campaigns)} campaign(s)",
                workspace_id=ws.id,
                user_id=user.id,
            )
            return RedirectResponse(
                f"/ui/settings?workspace_id={ws.id}&probed=1&flash="
                + quote(f"Found {len(campaigns)} campaign(s) — pick a world and Save")
                + "&kind=ok",
                status_code=303,
            )

        # plain save — resolve campaign name/slug if we can cheaply
        if campaign_id is not None:
            ws.kanka_campaign_id = campaign_id
            token = decrypt_secret(ws.kanka_token_enc)
            if ws.kanka_base_url and token:
                try:
                    campaigns = probe_campaigns(
                        ws.kanka_base_url,
                        token,
                        api_prefix=ws.kanka_api_prefix or "/1.0",
                    )
                    apply_campaign_record(ws, find_campaign(campaigns, campaign_id))
                except Exception:
                    pass
        db.commit()
        write_log(
            db,
            f"Workspace “{ws.name}” saved",
            workspace_id=ws.id,
            user_id=user.id,
        )
        return RedirectResponse(
            f"/ui/settings?workspace_id={ws.id}&flash="
            + quote("Settings saved")
            + "&kind=ok",
            status_code=303,
        )

    @app.get("/ui/keys", response_model=None)
    def ui_keys(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        keys = (
            db.query(ApiKey)
            .filter_by(user_id=user.id)
            .order_by(ApiKey.id.desc())
            .all()
        )
        return templates.TemplateResponse(
            request,
            "keys.html",
            _ctx(
                request,
                user=user,
                nav="keys",
                app_name=settings.app_name,
                keys=keys,
                new_key="",
            ),
        )

    @app.post("/ui/keys", response_model=None)
    def ui_keys_create(
        request: Request,
        name: str = Form(...),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _row, raw = create_api_key(db, user, name)
        write_log(db, f"API key created: {name}", user_id=user.id)
        keys = (
            db.query(ApiKey)
            .filter_by(user_id=user.id)
            .order_by(ApiKey.id.desc())
            .all()
        )
        return templates.TemplateResponse(
            request,
            "keys.html",
            _ctx(
                request,
                user=user,
                nav="keys",
                app_name=settings.app_name,
                keys=keys,
                new_key=raw,
                flash="Key created - copy it now",
                flash_kind="ok",
            ),
        )

    @app.post("/ui/keys/{key_id}/revoke")
    def ui_keys_revoke(
        key_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        key = db.get(ApiKey, key_id)
        if key is None or key.user_id != user.id:
            return RedirectResponse(
                "/ui/keys?flash=" + quote("Key not found") + "&kind=err",
                status_code=303,
            )
        revoke_api_key(db, key)
        write_log(db, f"API key revoked: {key.name}", user_id=user.id)
        return RedirectResponse(
            "/ui/keys?flash=" + quote("Key revoked") + "&kind=ok",
            status_code=303,
        )

    @app.get("/ui/logs", response_model=None)
    def ui_logs(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        ws_list = _user_workspaces(db, user)
        selected = request.query_params.get("workspace_id")
        selected_id = int(selected) if selected and selected.isdigit() else None
        q = db.query(AppLog).order_by(AppLog.id.desc())
        if selected_id is not None:
            require_workspace_member(selected_id, user, db)
            q = q.filter(AppLog.workspace_id == selected_id)
        elif not user.is_admin:
            ws_ids = [w.id for w in ws_list]
            q = q.filter(
                (AppLog.workspace_id.in_(ws_ids)) | (AppLog.user_id == user.id)
            )
        logs = q.limit(200).all()
        return templates.TemplateResponse(
            request,
            "logs.html",
            _ctx(
                request,
                user=user,
                nav="logs",
                app_name=settings.app_name,
                logs=logs,
                workspaces=ws_list,
                selected_workspace_id=selected_id,
            ),
        )

    return app


app = create_app()
