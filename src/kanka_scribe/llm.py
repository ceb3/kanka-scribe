from __future__ import annotations

import json
import logging
import re

import httpx

from kanka_scribe.entity_extract import EntityCandidate, chunk_transcript
from kanka_scribe.prompts import (
    build_chunk_messages,
    build_clean_chunk_messages,
    build_clean_merge_messages,
    build_detail_messages,
    build_extract_messages,
    build_merge_messages,
    build_messages,
    build_session_meta_messages,
    build_story_title_messages,
)
from kanka_scribe.session_notes import SessionMeta, parse_session_meta

logger = logging.getLogger(__name__)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I | re.M)


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    timeout: float = 600.0,
) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": model, "messages": messages, "stream": False}
    r = httpx.post(
        _chat_url(base_url), headers=headers, json=body, timeout=timeout
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def estimate_tokens(text: str) -> int:
    """Rough char/4 estimate used to decide whether to chunk."""
    return (len(text) + 3) // 4


def summarize(
    base_url: str,
    api_key: str,
    model: str,
    transcript: str,
    context: str = "",
    cast_block: str = "",
    context_length: int = 32768,
    timeout: float = 600.0,
    system_prompt: str | None = None,
) -> str:
    """Summarize a transcript, automatically chunking when it exceeds context."""
    transcript = (transcript or "").strip()
    if not transcript:
        return ""

    overhead = estimate_tokens(context) + estimate_tokens(cast_block) + 1536
    usable = max(1024, context_length - overhead)
    if estimate_tokens(transcript) <= usable:
        return chat(
            base_url,
            api_key,
            model,
            build_messages(
                transcript, context, cast_block, system_prompt=system_prompt
            ),
            timeout=timeout,
        )

    chunks = chunk_transcript(transcript, context_length)
    if len(chunks) <= 1:
        return chat(
            base_url,
            api_key,
            model,
            build_messages(
                transcript, context, cast_block, system_prompt=system_prompt
            ),
            timeout=timeout,
        )

    logger.info(
        "transcript ~%d tokens exceeds usable context %d; "
        "summarizing in %d chunks",
        estimate_tokens(transcript),
        usable,
        len(chunks),
    )
    partials: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        partial = chat(
            base_url,
            api_key,
            model,
            build_chunk_messages(chunk, i, len(chunks), context, cast_block),
            timeout=timeout,
        )
        partials.append(partial.strip())

    merged = "\n\n".join(p for p in partials if p)
    if estimate_tokens(merged) > usable:
        merge_chunks = chunk_transcript(merged, context_length)
        if len(merge_chunks) > 1:
            mid: list[str] = []
            for i, chunk in enumerate(merge_chunks, start=1):
                mid.append(
                    chat(
                        base_url,
                        api_key,
                        model,
                        build_chunk_messages(
                            chunk, i, len(merge_chunks), context, cast_block
                        ),
                        timeout=timeout,
                    ).strip()
                )
            partials = mid

    return chat(
        base_url,
        api_key,
        model,
        build_merge_messages(
            partials, context, cast_block, system_prompt=system_prompt
        ),
        timeout=timeout,
    )


def story_title(base_url: str, api_key: str, model: str, recap: str) -> str:
    raw = chat(base_url, api_key, model, build_story_title_messages(recap), timeout=120)
    line = raw.strip().splitlines()[0].strip().strip("\"'")
    for prefix in ("Title:", "title:"):
        if line.startswith(prefix):
            line = line[len(prefix) :].strip()
    return line[:80] or "Untitled Session"


def extract_session_meta(
    base_url: str,
    api_key: str,
    model: str,
    *,
    transcript: str,
    recap: str = "",
    cast_block: str = "",
    timeout: float = 120.0,
) -> SessionMeta:
    """Best-effort session metadata; Unknown fields when the model is unsure."""
    try:
        raw = chat(
            base_url,
            api_key,
            model,
            build_session_meta_messages(
                transcript=transcript, recap=recap, cast_block=cast_block
            ),
            timeout=timeout,
        )
        return parse_session_meta(raw)
    except Exception as exc:  # noqa: BLE001 — metadata is best-effort
        logger.warning("session meta extract failed: %s", exc)
        return SessionMeta()


def clean_transcript(
    base_url: str,
    api_key: str,
    model: str,
    transcript: str,
    *,
    cast_block: str = "",
    context_length: int = 32768,
    timeout: float = 600.0,
) -> str:
    """Strip OOC chatter; preserve speakers and timestamps. Chunk when needed."""
    transcript = (transcript or "").strip()
    if not transcript:
        return ""

    overhead = estimate_tokens(cast_block) + 1024
    usable = max(1024, context_length - overhead)
    chunks = chunk_transcript(transcript, context_length)
    if estimate_tokens(transcript) <= usable or len(chunks) <= 1:
        return chat(
            base_url,
            api_key,
            model,
            build_clean_chunk_messages(transcript, 1, 1, cast_block),
            timeout=timeout,
        ).strip()

    logger.info(
        "cleaning transcript in %d chunks (~%d tokens)",
        len(chunks),
        estimate_tokens(transcript),
    )
    partials: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        partials.append(
            chat(
                base_url,
                api_key,
                model,
                build_clean_chunk_messages(chunk, i, len(chunks), cast_block),
                timeout=timeout,
            ).strip()
        )
    merged = "\n\n".join(p for p in partials if p)
    if len(partials) == 1:
        return merged
    if estimate_tokens(merged) <= usable:
        return chat(
            base_url,
            api_key,
            model,
            build_clean_merge_messages(partials),
            timeout=timeout,
        ).strip()
    return merged


def _parse_entities(content: str) -> list[EntityCandidate]:
    text = _FENCE.sub("", content.strip()).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("entities root must be object")
    out: list[EntityCandidate] = []
    for item in data.get("entities", []) or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        aliases = item.get("aliases", [])
        evidence = item.get("evidence", [])
        if not isinstance(aliases, list):
            aliases = []
        if not isinstance(evidence, list):
            evidence = []
        out.append(
            EntityCandidate(
                type=str(item.get("type", "note")).strip().lower(),
                name=str(item["name"]).strip(),
                aliases=[str(a).strip() for a in aliases if str(a).strip()],
                summary=str(item.get("summary", "")).strip(),
                confidence=str(item.get("confidence", "low")).strip().lower(),
                evidence=[str(e).strip() for e in evidence if str(e).strip()],
            )
        )
    return out


def extract_entities_chunk(
    base_url: str,
    api_key: str,
    model: str,
    chunk: str,
    profile: str = "ce",
    cast_block: str = "",
) -> list[EntityCandidate]:
    messages = build_extract_messages(chunk, profile, cast_block=cast_block)
    last_err: Exception | None = None
    for _ in range(2):
        try:
            content = chat(base_url, api_key, model, messages)
            return _parse_entities(content)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, httpx.HTTPError) as exc:
            last_err = exc
            continue
    logger.warning("entity extract failed after retry: %s", last_err)
    return []


def _parse_detail_payload(content: str) -> tuple[list[EntityCandidate], list[dict], list[EntityCandidate]]:
    text = _FENCE.sub("", content.strip()).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("detail root must be object")
    details: list[EntityCandidate] = []
    for item in data.get("details") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        aliases = item.get("aliases") or []
        evidence = item.get("evidence") or []
        if not isinstance(aliases, list):
            aliases = []
        if not isinstance(evidence, list):
            evidence = []
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        details.append(
            EntityCandidate(
                type=str(item.get("type") or "note").strip().lower(),
                name=str(item["name"]).strip(),
                aliases=[str(a).strip() for a in aliases if str(a).strip()],
                summary=str(item.get("summary") or "").strip(),
                confidence="high",
                evidence=[str(e).strip() for e in evidence if str(e).strip()],
                fields=dict(fields),
            )
        )
    memberships: list[dict] = []
    for item in data.get("memberships") or []:
        if isinstance(item, dict) and item.get("character") and (
            item.get("organisation") or item.get("organization")
        ):
            memberships.append(item)
    events: list[EntityCandidate] = []
    for item in data.get("events") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        evidence = item.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = []
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        events.append(
            EntityCandidate(
                type="event",
                name=str(item["name"]).strip(),
                summary=str(item.get("summary") or "").strip(),
                confidence="medium",
                evidence=[str(e).strip() for e in evidence if str(e).strip()],
                fields=dict(fields),
            )
        )
    return details, memberships, events


def extract_entity_details_chunk(
    base_url: str,
    api_key: str,
    model: str,
    chunk: str,
    *,
    known_entities: list[dict],
    cast_block: str = "",
    entity_type_prompts: str | dict | None = None,
) -> tuple[list[EntityCandidate], list[dict], list[EntityCandidate]]:
    messages = build_detail_messages(
        chunk,
        known_entities=known_entities,
        cast_block=cast_block,
        entity_type_prompts=entity_type_prompts,
    )
    last_err: Exception | None = None
    for _ in range(2):
        try:
            content = chat(base_url, api_key, model, messages)
            return _parse_detail_payload(content)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, httpx.HTTPError) as exc:
            last_err = exc
            continue
    logger.warning("entity detail extract failed after retry: %s", last_err)
    return [], [], []
