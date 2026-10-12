from __future__ import annotations

from dataclasses import dataclass

import httpx

from kanka_scribe.entity_extract import normalize_name
from kanka_scribe.html_format import markdown_to_kanka_html
from kanka_scribe.kanka_http import kanka_request


@dataclass
class KankaResult:
    journal_id: int
    note_id: int
    journal_entity_id: int
    note_entity_id: int


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def probe_campaigns(base_url: str, token: str, api_prefix: str = "/1.0") -> list[dict]:
    prefix = "/" + api_prefix.strip("/")
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0) as client:
        r = kanka_request(
            client.get, f"{prefix}/campaigns", headers=_headers(token)
        )
        r.raise_for_status()
        return r.json().get("data", [])


def _get_pages(client: httpx.Client, path: str, headers: dict) -> list[dict]:
    records: list[dict] = []
    page = 1
    next_url: str | None = path
    while next_url:
        response = kanka_request(
            client.get,
            next_url,
            headers=headers,
            params={"page": page} if next_url == path else None,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", [])
        if not data:
            break
        records.extend(data)
        links = payload.get("links") or {}
        if links.get("next"):
            next_url = links["next"]
            continue
        meta = payload.get("meta") or {}
        if "last_page" in meta:
            current = meta.get("current_page", page)
            if current < meta["last_page"]:
                page = current + 1
                next_url = path
            else:
                break
        elif len(data) >= meta.get("per_page", 15):
            page += 1
            next_url = path
        else:
            break
    return records


def sanitize_cast_aliases(characters: list[dict]) -> list[dict]:
    """Drop aliases that collide with another Player Character's primary name.

    Campaign-agnostic: uses Kanka Type + names from this campaign's cast only.
    Non-PC rows (NPCs / untyped) may share nicknames without blocking PC aliases.
    """
    from kanka_scribe.kanka_entities import is_player_character_type

    pc_primary_norms = {
        normalize_name(str(ch.get("name") or ""))
        for ch in characters
        if str(ch.get("name") or "").strip()
        and is_player_character_type(ch.get("character_type"))
    }
    cleaned: list[dict] = []
    for ch in characters:
        name = str(ch.get("name") or "").strip()
        own = normalize_name(name)
        aliases: list[str] = []
        seen: set[str] = set()
        for raw in ch.get("aliases") or []:
            alias = str(raw or "").strip()
            if not alias:
                continue
            norm = normalize_name(alias)
            if not norm or norm == own:
                continue
            # Never let one PC's primary name be another's alias.
            if norm in pc_primary_norms and norm != own:
                continue
            if norm in seen:
                continue
            seen.add(norm)
            aliases.append(alias)
        row = dict(ch)
        row["name"] = name
        row["aliases"] = aliases
        cleaned.append(row)
    return cleaned


def fetch_characters_with_aliases(
    client: httpx.Client,
    campaign_id: int,
    token: str,
    *,
    api_prefix: str = "/1.0",
    alias_type_id: int = 3,
) -> list[dict]:
    """Return cast rows including character_type from Kanka's Type field.

    Keys: name, aliases, entity_id, module_id, is_private, character_type.
    Aliases that equal another character's primary name are stripped.
    """
    prefix = "/" + api_prefix.strip("/")
    headers = _headers(token)
    records = _get_pages(
        client, f"{prefix}/campaigns/{campaign_id}/characters", headers
    )
    out: list[dict] = []
    for record in records:
        entity_id = int(record["entity_id"])
        aliases: list[str] = []
        try:
            assets = _get_pages(
                client,
                f"{prefix}/campaigns/{campaign_id}/entities/{entity_id}/entity_assets",
                headers,
            )
            for asset in assets:
                if int(asset.get("type_id", 0)) != alias_type_id:
                    continue
                alias = str(asset.get("name") or "").strip()
                if alias:
                    aliases.append(alias)
        except httpx.HTTPError:
            pass
        char_type = record.get("type")
        out.append(
            {
                "name": str(record.get("name") or "").strip(),
                "aliases": aliases,
                "entity_id": entity_id,
                "module_id": int(record["id"]),
                "is_private": bool(record.get("is_private", False)),
                "character_type": str(char_type or "").strip(),
            }
        )
    return sanitize_cast_aliases(out)


def create_session_entities(
    client: httpx.Client,
    campaign_id: int,
    token: str,
    title: str,
    recap: str,
    transcript: str,
    api_prefix: str = "/1.0",
    archive_id: str | None = None,
    note_entry: str | None = None,
    campaign_slug: str = "",
    session_date: str = "",
) -> KankaResult:
    prefix = "/" + api_prefix.strip("/")
    journal_body: dict = {
        "name": title,
        "entry": markdown_to_kanka_html(
            recap, campaign_id=campaign_id, campaign_slug=campaign_slug
        ),
        "type": "Session Recap",
    }
    if session_date and session_date != "Unknown":
        journal_body["date"] = session_date
    j = kanka_request(
        client.post,
        f"{prefix}/campaigns/{campaign_id}/journals",
        headers=_headers(token),
        json=journal_body,
    )
    j.raise_for_status()
    jdata = j.json()["data"]
    if note_entry is None:
        note_entry = transcript
        if archive_id:
            note_entry = (
                f"{transcript.rstrip()}\n\n---\nSource archive: `{archive_id}`\n"
            )
    n = kanka_request(
        client.post,
        f"{prefix}/campaigns/{campaign_id}/notes",
        headers=_headers(token),
        json={
            "name": f"{title} — Transcript",
            "entry": markdown_to_kanka_html(
                note_entry, campaign_id=campaign_id, campaign_slug=campaign_slug
            ),
            "is_private": True,
        },
    )
    n.raise_for_status()
    ndata = n.json()["data"]
    return KankaResult(
        journal_id=int(jdata["id"]),
        note_id=int(ndata["id"]),
        journal_entity_id=int(jdata["entity_id"]),
        note_entity_id=int(ndata["entity_id"]),
    )
