from __future__ import annotations

import json
import logging
from dataclasses import asdict

import httpx
from sqlalchemy.orm import Session

from kanka_scribe.applog import write_log
from kanka_scribe.config import default_kanka_public_url
from kanka_scribe.discord_notify import (
    build_discord_message,
    build_name_to_url,
    post_webhook,
)
from kanka_scribe.entity_pipeline import run_phase_a, run_phase_b
from kanka_scribe.kanka_campaign import apply_campaign_record, find_campaign
from kanka_scribe.kanka_client import (
    create_session_entities,
    fetch_characters_with_aliases,
    probe_campaigns,
)
from kanka_scribe.llm import (
    clean_transcript,
    extract_session_meta,
    story_title,
    summarize,
)
from kanka_scribe.models import Job, Workspace
from kanka_scribe.prompts import format_cast_block
from kanka_scribe.registry import alias_asset_type_id
from kanka_scribe.secrets import decrypt_secret
from kanka_scribe.session_notes import (
    build_transcript_note,
    enrich_meta_from_cast,
    enrich_meta_from_recap,
    enrich_meta_from_title,
    linkify_document,
)
from kanka_scribe.transcript_clean import apply_timing_to_meta, remap_speakers

logger = logging.getLogger(__name__)


def run_ingest_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    workspace = db.get(Workspace, job.workspace_id)
    if workspace is None:
        raise ValueError("workspace missing")

    job.status = "running"
    job.error = ""
    db.commit()
    write_log(
        db,
        f"Job #{job.id} started ({job.source})",
        workspace_id=workspace.id,
        job_id=job.id,
    )

    try:
        token = decrypt_secret(workspace.kanka_token_enc)
        llm_key = decrypt_secret(workspace.llm_api_key_enc)
        if not workspace.kanka_base_url or not token or not workspace.kanka_campaign_id:
            raise RuntimeError("workspace Kanka destination not configured")
        if not workspace.llm_base_url or not workspace.llm_model:
            raise RuntimeError("workspace LLM not configured")

        transcript = (job.transcript or "").strip()
        if not transcript:
            raise RuntimeError("empty transcript")

        context_length = workspace.llm_context_length or 32768
        profile = workspace.kanka_profile or "ce"
        api_prefix = workspace.kanka_api_prefix or "/1.0"
        campaign_id = int(workspace.kanka_campaign_id)
        public_base = (
            workspace.kanka_public_url or default_kanka_public_url()
        ).rstrip("/")

        with httpx.Client(
            base_url=workspace.kanka_base_url.rstrip("/"), timeout=120.0
        ) as client:
            # Refresh public slug from Kanka (pretty URLs like /w/kelmorth)
            try:
                campaigns = probe_campaigns(
                    workspace.kanka_base_url,
                    token,
                    api_prefix=api_prefix,
                )
                if apply_campaign_record(
                    workspace, find_campaign(campaigns, campaign_id)
                ):
                    db.commit()
                    write_log(
                        db,
                        (
                            f"Job #{job.id}: campaign public path "
                            f"/w/{(workspace.kanka_campaign_slug or campaign_id)}"
                        ),
                        workspace_id=workspace.id,
                        job_id=job.id,
                    )
            except Exception as exc:
                write_log(
                    db,
                    f"Job #{job.id}: campaign slug refresh skipped ({exc})",
                    level="warning",
                    workspace_id=workspace.id,
                    job_id=job.id,
                )
            campaign_slug = (workspace.kanka_campaign_slug or "").strip()

            write_log(
                db,
                f"Job #{job.id}: loading Kanka character cast",
                workspace_id=workspace.id,
                job_id=job.id,
            )
            characters = fetch_characters_with_aliases(
                client,
                campaign_id,
                token,
                api_prefix=api_prefix,
                alias_type_id=alias_asset_type_id(profile),
            )
            cast_block = format_cast_block(characters)
            write_log(
                db,
                f"Job #{job.id}: cast has {len(characters)} character(s)",
                workspace_id=workspace.id,
                job_id=job.id,
            )

            original_len = len(transcript)
            remapped = remap_speakers(transcript, characters)
            write_log(
                db,
                f"Job #{job.id}: cleaning transcript (speakers + OOC strip)",
                workspace_id=workspace.id,
                job_id=job.id,
            )
            cleaned = clean_transcript(
                workspace.llm_base_url,
                llm_key,
                workspace.llm_model,
                remapped,
                cast_block=cast_block,
                context_length=context_length,
            ).strip()
            if not cleaned:
                cleaned = remapped
            # Guard: unlabeled Notion/meeting pastes sometimes get summarized to
            # near-nothing by the cleaner — keep the remapped original instead.
            min_keep = max(500, int(original_len * 0.25)) if original_len >= 1000 else 1
            if original_len >= 1000 and len(cleaned) < min_keep:
                write_log(
                    db,
                    (
                        f"Job #{job.id}: clean shrunk too far "
                        f"({original_len}→{len(cleaned)}); keeping original"
                    ),
                    workspace_id=workspace.id,
                    job_id=job.id,
                )
                cleaned = remapped
            transcript = cleaned
            job.transcript = transcript
            db.commit()
            write_log(
                db,
                (
                    f"Job #{job.id}: transcript cleaned "
                    f"{original_len}→{len(transcript)} chars"
                ),
                workspace_id=workspace.id,
                job_id=job.id,
            )

            user_recap = (job.recap_markdown or "").strip()
            if job.source in {"paste", "upload", "manual", "notion"} and user_recap:
                recap = user_recap
                write_log(
                    db,
                    f"Job #{job.id}: using provided recap",
                    workspace_id=workspace.id,
                    job_id=job.id,
                )
            else:
                write_log(
                    db,
                    f"Job #{job.id}: Goblin Scribe summarizing (~{len(transcript)} chars)",
                    workspace_id=workspace.id,
                    job_id=job.id,
                )
                recap = summarize(
                    workspace.llm_base_url,
                    llm_key,
                    workspace.llm_model,
                    transcript,
                    cast_block=cast_block,
                    context_length=context_length,
                    system_prompt=workspace.recap_system_prompt or "",
                )
                job.recap_markdown = recap
                db.commit()

            title = (job.title or "").strip()
            if not title:
                title = story_title(
                    workspace.llm_base_url, llm_key, workspace.llm_model, recap
                )
                job.title = title
                db.commit()

            write_log(
                db,
                f"Job #{job.id}: extracting session metadata",
                workspace_id=workspace.id,
                job_id=job.id,
            )
            meta = extract_session_meta(
                workspace.llm_base_url,
                llm_key,
                workspace.llm_model,
                transcript=transcript,
                recap=recap,
                cast_block=cast_block,
            )
            meta = enrich_meta_from_recap(meta, recap)
            meta = enrich_meta_from_title(meta, title)
            meta = enrich_meta_from_cast(meta, characters, recap)
            apply_timing_to_meta(meta, transcript)
            write_log(
                db,
                (
                    f"Job #{job.id}: session meta "
                    f"session={meta.session} date={meta.date}"
                ),
                workspace_id=workspace.id,
                job_id=job.id,
            )

            write_log(
                db,
                f"Job #{job.id}: Phase A — match/create entities from recap + cast",
                workspace_id=workspace.id,
                job_id=job.id,
            )
            phase_a = run_phase_a(
                client,
                campaign_id=campaign_id,
                token=token,
                session_title=title,
                recap=recap,
                cast=characters,
                cast_block=cast_block,
                llm_base_url=workspace.llm_base_url,
                llm_key=llm_key,
                llm_model=workspace.llm_model,
                context_length=context_length,
                profile=profile,
                api_prefix=api_prefix,
                campaign_slug=campaign_slug,
                session_date=meta.date if meta.date != "Unknown" else "",
            )
            write_log(
                db,
                (
                    f"Job #{job.id}: Phase A "
                    f"+{len(phase_a.sync['created'])}/~{len(phase_a.sync['updated'])} "
                    f"errors={len(phase_a.sync['errors'])}"
                ),
                workspace_id=workspace.id,
                job_id=job.id,
            )

            name_to_url = build_name_to_url(
                public_base=public_base,
                campaign_id=campaign_id,
                cast=characters,
                entities=phase_a.touched,
                campaign_slug=campaign_slug,
            )
            linked_recap = linkify_document(recap, name_to_url)
            job.recap_markdown = linked_recap
            db.commit()

            note_entry = build_transcript_note(
                transcript=transcript,
                meta=meta,
                source=job.source or "",
                name_to_url=name_to_url,
                archive_id=None,
            )

            write_log(
                db,
                f"Job #{job.id}: writing journal \"{title}\" to Kanka",
                workspace_id=workspace.id,
                job_id=job.id,
            )
            kanka = create_session_entities(
                client,
                campaign_id,
                token,
                title,
                linked_recap,
                transcript,
                api_prefix=api_prefix,
                note_entry=note_entry,
                campaign_slug=campaign_slug,
                session_date=meta.date if meta.date != "Unknown" else "",
            )

            write_log(
                db,
                f"Job #{job.id}: Phase B — transcript details, orgs, timeline",
                workspace_id=workspace.id,
                job_id=job.id,
            )
            phase_b = run_phase_b(
                client,
                campaign_id=campaign_id,
                token=token,
                session_title=title,
                recap=linked_recap,
                transcript=transcript,
                cast_block=cast_block,
                phase_a=phase_a,
                llm_base_url=workspace.llm_base_url,
                llm_key=llm_key,
                llm_model=workspace.llm_model,
                context_length=context_length,
                profile=profile,
                api_prefix=api_prefix,
                journal_entity_id=kanka.journal_entity_id,
                session_meta=meta,
                campaign_slug=campaign_slug,
                entity_type_prompts=workspace.entity_type_prompts or "",
            )
            write_log(
                db,
                (
                    f"Job #{job.id}: Phase B posts "
                    f"+{len(phase_b.sync.get('created') or [])}/"
                    f"~{len(phase_b.sync.get('updated') or [])}; "
                    f"orgs +{len(phase_b.memberships.get('created') or [])}; "
                    f"timeline={phase_b.timeline.get('created')}"
                ),
                workspace_id=workspace.id,
                job_id=job.id,
            )

            entity_payload = {
                "created": list(phase_a.sync["created"])
                + list(phase_b.sync.get("created") or []),
                "updated": list(phase_a.sync["updated"])
                + list(phase_b.sync.get("updated") or []),
                "errors": list(phase_a.sync["errors"])
                + list(phase_b.sync.get("errors") or [])
                + list(phase_b.errors),
                "memberships": phase_b.memberships,
                "timeline": phase_b.timeline,
                "calendar": phase_b.calendar,
            }
            touched = entity_payload["created"] + entity_payload["updated"]
            merged = phase_a.candidates

        discord_entities = list(touched)
        # Ensure cast characters are available for Discord linkify too
        for ch in characters:
            if ch.get("entity_id") and ch.get("name"):
                discord_entities.append(
                    {"name": ch["name"], "entity_id": ch["entity_id"]}
                )

        discord_payload: dict = {"posted": False, "content": "", "error": ""}
        webhook = decrypt_secret(workspace.discord_webhook_enc)
        if workspace.discord_enabled and webhook:
            msg = build_discord_message(
                title=title,
                recap=linked_recap,
                public_base=public_base,
                campaign_id=campaign_id,
                campaign_slug=campaign_slug,
                journal_entity_id=kanka.journal_entity_id,
                note_entity_id=kanka.note_entity_id,
                entities=discord_entities,
            )
            try:
                post_webhook(
                    webhook,
                    msg,
                    username=workspace.discord_username or "Goblin Scribe",
                )
                discord_payload = {"posted": True, "content": msg, "error": ""}
                write_log(
                    db,
                    f"Job #{job.id}: posted Discord recap",
                    workspace_id=workspace.id,
                    job_id=job.id,
                )
            except Exception as exc:
                discord_payload = {"posted": False, "content": msg, "error": str(exc)}
                write_log(
                    db,
                    f"Job #{job.id}: Discord post failed: {exc}",
                    level="error",
                    workspace_id=workspace.id,
                    job_id=job.id,
                )

        result = {
            "journal_id": kanka.journal_id,
            "note_id": kanka.note_id,
            "journal_entity_id": kanka.journal_entity_id,
            "note_entity_id": kanka.note_entity_id,
            "entity_sync": entity_payload,
            "entities_considered": [asdict(c) for c in merged],
            "discord": discord_payload,
            "cast_count": len(characters),
            "session_meta": {
                "session": meta.session,
                "date": meta.date,
                "time": meta.time,
                "start": meta.start,
                "end": meta.end,
                "duration": meta.duration,
                "participants": meta.participants,
                "locations": meta.locations,
            },
            "transcript_chars": {"original": original_len, "cleaned": len(transcript)},
        }
        job.result_json = json.dumps(result)
        job.status = "completed"
        db.commit()
        write_log(
            db,
            (
                f"Job #{job.id} completed — journal {kanka.journal_id}, "
                f"entities +{len(entity_payload['created'])}/"
                f"~{len(entity_payload['updated'])}"
            ),
            workspace_id=workspace.id,
            job_id=job.id,
        )
        return job
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        job.status = "failed"
        job.error = str(exc)
        db.commit()
        write_log(
            db,
            f"Job #{job_id} failed: {exc}",
            level="error",
            workspace_id=workspace.id,
            job_id=job_id,
        )
        return job
