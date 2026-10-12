"""Two-phase entity sync: recap stubs → transcript details + orgs/time."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

import httpx

from kanka_scribe.entity_extract import EntityCandidate, chunk_transcript, merge_candidates
from kanka_scribe.html_format import html_entry, markdown_to_kanka_html
from kanka_scribe.kanka_entities import (
    ensure_journal_calendar_reminder,
    ensure_session_timeline_element,
    link_organisation_members,
    memberships_from_character_fields,
    sync_entities,
)
from kanka_scribe.llm import extract_entities_chunk, extract_entity_details_chunk
from kanka_scribe.recap_entities import candidates_from_cast, candidates_from_recap
from kanka_scribe.session_notes import SessionMeta

logger = logging.getLogger(__name__)


def normalize_key(name: str) -> str:
    return " ".join((name or "").strip().casefold().split())


@dataclass
class PhaseAResult:
    sync: dict
    candidates: list[EntityCandidate]
    touched: list[dict]

    def as_dict(self) -> dict:
        return {
            "created": self.sync.get("created") or [],
            "updated": self.sync.get("updated") or [],
            "errors": self.sync.get("errors") or [],
            "candidates": [asdict(c) for c in self.candidates],
        }


@dataclass
class PhaseBResult:
    sync: dict = field(default_factory=dict)
    memberships: dict = field(default_factory=dict)
    timeline: dict = field(default_factory=dict)
    calendar: dict = field(default_factory=dict)
    candidates: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _short_summary_markdown(recap: str) -> str:
    lines = (recap or "").splitlines()
    capturing = False
    out: list[str] = []
    for line in lines:
        if line.strip().lower().startswith("### short summary"):
            capturing = True
            continue
        if capturing and line.strip().startswith("### "):
            break
        if capturing:
            out.append(line)
    return "\n".join(out).strip() or (recap or "")[:1200]


def run_phase_a(
    client: httpx.Client,
    *,
    campaign_id: int,
    token: str,
    session_title: str,
    recap: str,
    cast: list[dict],
    cast_block: str,
    llm_base_url: str,
    llm_key: str,
    llm_model: str,
    context_length: int,
    profile: str,
    api_prefix: str,
    campaign_slug: str = "",
    session_date: str = "",
) -> PhaseAResult:
    found = list(candidates_from_cast(cast)) + list(candidates_from_recap(recap))
    if recap.strip():
        for chunk in chunk_transcript(recap, context_length):
            found.extend(
                extract_entities_chunk(
                    llm_base_url,
                    llm_key,
                    llm_model,
                    chunk,
                    profile=profile,
                    cast_block=cast_block,
                )
            )
    merged = merge_candidates(found)
    sync = sync_entities(
        client,
        campaign_id,
        token,
        session_title,
        merged,
        api_prefix=api_prefix,
        profile=profile,
        write_posts=False,
        create_missing=True,
        campaign_slug=campaign_slug,
        session_date=session_date,
    )
    touched = list(sync.created) + list(sync.updated)
    return PhaseAResult(
        sync={
            "created": sync.created,
            "updated": sync.updated,
            "errors": sync.errors,
        },
        candidates=merged,
        touched=touched,
    )


def run_phase_b(
    client: httpx.Client,
    *,
    campaign_id: int,
    token: str,
    session_title: str,
    recap: str,
    transcript: str,
    cast_block: str,
    phase_a: PhaseAResult,
    llm_base_url: str,
    llm_key: str,
    llm_model: str,
    context_length: int,
    profile: str,
    api_prefix: str,
    journal_entity_id: int | None,
    session_meta: SessionMeta | None = None,
    campaign_slug: str = "",
    entity_type_prompts: str | dict | None = None,
) -> PhaseBResult:
    result = PhaseBResult()
    meta = session_meta or SessionMeta()

    known = [
        {
            "name": r["name"],
            "type": r.get("module") or "",
            "entity_id": r.get("entity_id"),
        }
        for r in phase_a.touched
        if r.get("name")
    ]
    seen = {normalize_key(k["name"]) for k in known}
    for c in phase_a.candidates:
        if normalize_key(c.name) not in seen:
            known.append({"name": c.name, "type": c.type})
            seen.add(normalize_key(c.name))

    detail_candidates: list[EntityCandidate] = []
    memberships: list[dict] = []
    event_candidates: list[EntityCandidate] = []
    if transcript.strip() and known:
        for chunk in chunk_transcript(transcript, context_length):
            details, mems, events = extract_entity_details_chunk(
                llm_base_url,
                llm_key,
                llm_model,
                chunk,
                known_entities=known,
                cast_block=cast_block,
                entity_type_prompts=entity_type_prompts,
            )
            detail_candidates.extend(details)
            memberships.extend(mems)
            event_candidates.extend(events)

    event_merged = merge_candidates(event_candidates)
    if event_merged:
        sync_events = sync_entities(
            client,
            campaign_id,
            token,
            session_title,
            event_merged,
            api_prefix=api_prefix,
            profile=profile,
            write_posts=False,
            create_missing=True,
            campaign_slug=campaign_slug,
            session_date=meta.date if meta.date != "Unknown" else "",
        )
        phase_a.sync["created"] = list(phase_a.sync["created"]) + list(
            sync_events.created
        )
        phase_a.sync["updated"] = list(phase_a.sync["updated"]) + list(
            sync_events.updated
        )
        phase_a.touched.extend(sync_events.created)
        phase_a.touched.extend(sync_events.updated)

    by_key: dict[tuple[str, str], EntityCandidate] = {}
    for c in list(phase_a.candidates) + list(event_merged):
        by_key[(c.type, normalize_key(c.name))] = c
    for c in merge_candidates(detail_candidates):
        by_key[(c.type, normalize_key(c.name))] = c
    post_list = list(by_key.values())
    result.candidates = [asdict(c) for c in post_list]

    sync_b = sync_entities(
        client,
        campaign_id,
        token,
        session_title,
        post_list,
        api_prefix=api_prefix,
        profile=profile,
        write_posts=True,
        create_missing=True,
        campaign_slug=campaign_slug,
        session_date=meta.date if meta.date != "Unknown" else "",
    )
    result.sync = {
        "created": sync_b.created,
        "updated": sync_b.updated,
        "errors": sync_b.errors,
    }

    # Merge memberships from detail JSON + character fields.organisations[]
    memberships.extend(memberships_from_character_fields(detail_candidates))
    memberships.extend(memberships_from_character_fields(post_list))
    # Deduplicate by character|org
    seen_mem: set[str] = set()
    deduped_mems: list[dict] = []
    for item in memberships:
        key = (
            f"{str(item.get('character') or '').casefold()}|"
            f"{str(item.get('organisation') or item.get('organization') or '').casefold()}"
        )
        if not key.strip("|") or key in seen_mem:
            continue
        seen_mem.add(key)
        deduped_mems.append(item)

    result.memberships = link_organisation_members(
        client,
        campaign_id,
        token,
        deduped_mems,
        api_prefix=api_prefix,
        profile=profile,
        create_missing_orgs=True,
    )

    summary_md = _short_summary_markdown(recap)
    try:
        result.timeline = ensure_session_timeline_element(
            client,
            campaign_id,
            token,
            session_title=session_title,
            summary_html=markdown_to_kanka_html(
                summary_md, campaign_id=campaign_id, campaign_slug=campaign_slug
            )
            or html_entry(
                summary_md, [], campaign_id=campaign_id, campaign_slug=campaign_slug
            ),
            journal_entity_id=journal_entity_id,
            session_date=meta.date if meta.date != "Unknown" else "",
            api_prefix=api_prefix,
            profile=profile,
        )
    except Exception as exc:
        logger.warning("timeline element failed: %s", exc)
        result.errors.append(f"timeline: {exc}")
        result.timeline = {"created": False, "error": str(exc)}

    if journal_entity_id and meta.date and meta.date != "Unknown":
        try:
            result.calendar = ensure_journal_calendar_reminder(
                client,
                campaign_id,
                token,
                journal_entity_id=journal_entity_id,
                iso_date=meta.date,
                api_prefix=api_prefix,
            )
        except Exception as exc:
            logger.warning("calendar reminder failed: %s", exc)
            result.errors.append(f"calendar: {exc}")
            result.calendar = {"created": False, "error": str(exc)}
    else:
        result.calendar = {"created": False, "reason": "no_session_date"}

    return result
