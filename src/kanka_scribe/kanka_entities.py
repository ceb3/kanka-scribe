from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from html import escape

import httpx

from kanka_scribe.entity_extract import EntityCandidate, normalize_name
from kanka_scribe.html_format import html_entry
from kanka_scribe.kanka_http import kanka_request
from kanka_scribe.registry import (
    alias_asset_type_id,
    load_profile,
    module_path,
    visibility_id,
)
from kanka_scribe.session_notes import normalize_iso_date


def _request_with_retry(method, url: str, *, retries: int = 8, **kwargs):
    """Pace + retry Kanka HTTP calls (shared client-side rate limit)."""
    return kanka_request(method, url, retries=retries, **kwargs)


@dataclass
class EntityRef:
    module: str
    module_id: int
    entity_id: int
    name: str
    is_private: bool
    # Module Type string from Kanka (e.g. character "Player Character" / "NPC").
    character_type: str = ""


@dataclass
class SyncResult:
    created: list[dict] = field(default_factory=list)
    updated: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get_pages(
    client: httpx.Client, path: str, headers: dict
) -> list[dict]:
    records: list[dict] = []
    page = 1
    next_url: str | None = path
    while next_url:
        response = _request_with_retry(
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
        if "next" in links:
            linked_next = links["next"]
            if linked_next:
                next_url = linked_next
                continue
            break

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


def _entity_ref(module: str, data: dict) -> EntityRef:
    return EntityRef(
        module=module,
        module_id=int(data["id"]),
        entity_id=int(data["entity_id"]),
        name=data["name"],
        is_private=bool(data.get("is_private", False)),
        character_type=str(data.get("type") or "").strip(),
    )


def _prefer_unique_pc(refs: list[EntityRef]) -> EntityRef | None:
    """If multiple refs tie, return the sole Player Character when unique."""
    unique = _unique_refs(refs)
    if len(unique) == 1:
        return unique[0]
    pcs = [r for r in unique if is_player_character_type(r.character_type)]
    if len(pcs) == 1:
        return pcs[0]
    return None


def _lookup_module_ids(
    client: httpx.Client,
    *,
    campaign_id: int,
    prefix: str,
    headers: dict,
    profile: str,
    module: str,
    names: list[str],
    cache: dict,
) -> list[int]:
    """Resolve entity/module names to module ids (locations.id, races.id, …)."""
    if not names:
        return []
    collection = module_path(profile, module)
    if not collection:
        return []
    key = f"nameindex:{module}"
    if key not in cache:
        records = _get_pages(
            client, f"{prefix}/campaigns/{campaign_id}/{collection}", headers
        )
        index: dict[str, int] = {}
        for row in records:
            name = str(row.get("name") or "").strip()
            if name and row.get("id") is not None:
                index[normalize_name(name)] = int(row["id"])
        cache[key] = index
    index = cache[key]
    out: list[int] = []
    seen: set[int] = set()
    for name in names:
        mid = index.get(normalize_name(str(name)))
        if mid is not None and mid not in seen:
            out.append(mid)
            seen.add(mid)
    return out


def _lookup_entity_ids(
    client: httpx.Client,
    *,
    campaign_id: int,
    prefix: str,
    headers: dict,
    profile: str,
    module: str,
    names: list[str],
    cache: dict,
) -> list[int]:
    """Resolve names to entity_id values (for quest instigator, item creators)."""
    if not names:
        return []
    collection = module_path(profile, module)
    if not collection:
        return []
    key = f"entityindex:{module}"
    if key not in cache:
        records = _get_pages(
            client, f"{prefix}/campaigns/{campaign_id}/{collection}", headers
        )
        index: dict[str, int] = {}
        for row in records:
            name = str(row.get("name") or "").strip()
            eid = row.get("entity_id")
            if name and eid is not None:
                index[normalize_name(name)] = int(eid)
        cache[key] = index
    index = cache[key]
    out: list[int] = []
    seen: set[int] = set()
    for name in names:
        eid = index.get(normalize_name(str(name)))
        if eid is not None and eid not in seen:
            out.append(eid)
            seen.add(eid)
    return out


# Allowed / preferred Kanka "Type" values per module (campaign conventions).
CHARACTER_TYPES = {"NPC", "Player Character", "Deity"}


def is_player_character_type(raw: str | None) -> bool:
    """True when Kanka character Type normalizes to Player Character."""
    text = str(raw or "").strip()
    if not text:
        return False
    return normalize_module_type("character", text) == "Player Character"


# Closed sets: normalize strictly onto these values.
QUEST_TYPES = {"Character Arc", "Sidequest", "Main"}
ITEM_TYPES = {"Weapon", "Potion", "Artifact"}
# Open-ish sets: prefer these labels; keep a close match or the LLM string.
LOCATION_TYPES = {
    "City",
    "Kingdom",
    "Ruin",
    "Village",
    "Town",
    "District",
    "Building",
    "Landmark",
    "Wilderness",
    "Dungeon",
    "Plane",
    "Region",
    "Forest",
    "Mountain",
    "River",
    "Coast",
    "Island",
    "Keep",
    "Temple",
    "Tavern",
}
ORGANISATION_TYPES = {
    "Cult",
    "Gang",
    "Rebellion",
    "Fandom",
    "Military",
    "Guild",
    "Religion",
    "Government",
    "Tribe",
    "Company",
    "Order",
    "Cabal",
    "Church",
    "Cartel",
}
CREATURE_TYPES = {
    "Herbivore",
    "Aquatic",
    "Mythical",
    "Carnivore",
    "Omnivore",
    "Beast",
    "Humanoid",
    "Undead",
    "Dragon",
    "Aberration",
    "Elemental",
    "Fiend",
    "Celestial",
    "Construct",
    "Plant",
    "Monstrosity",
    "Insect",
    "Bird",
    "Swarm",
}
EVENT_TYPES = {
    "Battle",
    "Ambush",
    "Discovery",
    "Ceremony",
    "Death",
    "Journey",
    "Negotiation",
    "Disaster",
    "Other",
}
# Modules that must map onto the closed vocabulary (no freeform passthrough).
_CLOSED_TYPE_MODULES = {"character", "quest", "item"}

_MODULE_TYPES: dict[str, set[str]] = {
    "character": CHARACTER_TYPES,
    "location": LOCATION_TYPES,
    "organisation": ORGANISATION_TYPES,
    "creature": CREATURE_TYPES,
    "quest": QUEST_TYPES,
    "item": ITEM_TYPES,
    "event": EVENT_TYPES,
}


def normalize_module_type(module: str, raw: str) -> str:
    """Map LLM type strings onto the allowed vocabulary for that module."""
    text = (raw or "").strip()
    if not text:
        return ""
    allowed = _MODULE_TYPES.get(module)
    if not allowed:
        return text
    # Exact / casefold match
    for option in allowed:
        if text.casefold() == option.casefold():
            return option
    key = text.casefold()
    if module == "character":
        if key in {"pc", "player", "player-character", "playercharacter"}:
            return "Player Character"
        if key in {"god", "goddess", "divine"}:
            return "Deity"
        return "NPC"
    if module == "quest":
        if key in {"side", "side quest", "sidequest"}:
            return "Sidequest"
        if key in {"main", "main quest", "primary"}:
            return "Main"
        if "arc" in key or "personal" in key:
            return "Character Arc"
        return "Sidequest"
    if module == "item":
        if any(w in key for w in ("weapon", "sword", "bow", "axe", "dagger", "blade")):
            return "Weapon"
        if any(w in key for w in ("potion", "elixir", "philter", "vial")):
            return "Potion"
        return "Artifact"
    # Fuzzy contains for open vocabularies
    for option in allowed:
        if option.casefold() in key or key in option.casefold():
            return option
    # Open modules: keep the LLM label (title-cased) rather than forcing Other
    if module not in _CLOSED_TYPE_MODULES:
        return text[:45]
    if "Other" in allowed:
        return "Other"
    return text


def memberships_from_character_fields(
    candidates: list[EntityCandidate],
) -> list[dict]:
    """Pull organisations[] / organisation from character detail fields."""
    out: list[dict] = []
    for cand in candidates:
        if cand.type.strip().lower() != "character":
            continue
        fields = cand.fields or {}
        orgs = fields.get("organisations") or fields.get("organizations")
        if orgs is None and fields.get("organisation"):
            orgs = [fields.get("organisation")]
        if not isinstance(orgs, list):
            continue
        for item in orgs:
            if isinstance(item, str) and item.strip():
                out.append(
                    {
                        "character": cand.name,
                        "organisation": item.strip(),
                        "role": "member",
                    }
                )
            elif isinstance(item, dict):
                name = str(
                    item.get("name")
                    or item.get("organisation")
                    or item.get("organization")
                    or ""
                ).strip()
                role = str(item.get("role") or "member").strip() or "member"
                if name:
                    out.append(
                        {
                            "character": cand.name,
                            "organisation": name,
                            "role": role,
                        }
                    )
    return out


def _trait_arrays(traits: object) -> tuple[list[str], list[str]]:
    names: list[str] = []
    entries: list[str] = []
    if not isinstance(traits, list):
        return names, entries
    for item in traits:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            entry = str(item.get("entry") or item.get("value") or "").strip()
            if name and entry:
                names.append(name[:45])
                entries.append(entry)
        elif isinstance(item, str) and ":" in item:
            name, _, entry = item.partition(":")
            name, entry = name.strip(), entry.strip()
            if name and entry:
                names.append(name[:45])
                entries.append(entry)
    return names, entries


def _build_metadata_payload(
    client: httpx.Client,
    *,
    campaign_id: int,
    prefix: str,
    headers: dict,
    profile: str,
    module: str,
    fields: dict,
    session_date: str = "",
    cache: dict,
) -> dict:
    """Map LLM fields → Kanka create/update JSON for this module."""
    fields = fields or {}
    body: dict = {}

    def s(key: str, *aliases: str) -> str:
        for k in (key, *aliases):
            val = fields.get(k)
            if isinstance(val, str) and val.strip() and val.strip().lower() not in {
                "unknown",
                "null",
                "none",
                "n/a",
            }:
                return val.strip()
        return ""

    def name_list(key: str, *aliases: str) -> list[str]:
        for k in (key, *aliases):
            val = fields.get(k)
            if isinstance(val, list):
                return [str(x).strip() for x in val if str(x).strip()]
            if isinstance(val, str) and val.strip():
                return [val.strip()]
        return []

    raw_type = s("type")
    type_val = normalize_module_type(module, raw_type) if raw_type else ""
    if type_val:
        body["type"] = type_val

    if module == "character":
        title = s("title")
        # If LLM stuffed a job/role into type, keep it as title when title empty
        if not title and raw_type and normalize_module_type("character", raw_type) == "NPC":
            if raw_type.casefold() not in {"npc", "player character", "deity", "pc"}:
                title = raw_type
        if title:
            body["title"] = title
        if s("age"):
            body["age"] = s("age")
        if s("sex", "gender"):
            body["sex"] = s("sex", "gender")
        if s("pronouns"):
            body["pronouns"] = s("pronouns")
        locs = _lookup_module_ids(
            client,
            campaign_id=campaign_id,
            prefix=prefix,
            headers=headers,
            profile=profile,
            module="location",
            names=name_list("locations", "location"),
            cache=cache,
        )
        if locs:
            body["locations"] = locs
        races = _lookup_module_ids(
            client,
            campaign_id=campaign_id,
            prefix=prefix,
            headers=headers,
            profile=profile,
            module="race",
            names=name_list("races", "race"),
            cache=cache,
        )
        if races:
            body["races"] = races
        an, ae = _trait_arrays(fields.get("appearance"))
        if an:
            body["appearance_name"] = an
            body["appearance_entry"] = ae
        pn, pe = _trait_arrays(fields.get("personality"))
        if pn:
            body["personality_name"] = pn
            body["personality_entry"] = pe

    elif module == "location":
        parent = s("parent", "parent_location")
        if parent:
            ids = _lookup_entity_ids(
                client,
                campaign_id=campaign_id,
                prefix=prefix,
                headers=headers,
                profile=profile,
                module="location",
                names=[parent],
                cache=cache,
            )
            if ids:
                body["parent_id"] = ids[0]

    elif module == "organisation":
        locs = _lookup_module_ids(
            client,
            campaign_id=campaign_id,
            prefix=prefix,
            headers=headers,
            profile=profile,
            module="location",
            names=name_list("locations", "location"),
            cache=cache,
        )
        if locs:
            body["locations"] = locs

    elif module == "creature":
        locs = _lookup_module_ids(
            client,
            campaign_id=campaign_id,
            prefix=prefix,
            headers=headers,
            profile=profile,
            module="location",
            names=name_list("locations", "location"),
            cache=cache,
        )
        if locs:
            body["locations"] = locs

    elif module == "quest":
        instigator = s("instigator", "giver", "quest_giver")
        if instigator:
            ids = _lookup_entity_ids(
                client,
                campaign_id=campaign_id,
                prefix=prefix,
                headers=headers,
                profile=profile,
                module="character",
                names=[instigator],
                cache=cache,
            )
            if ids:
                body["instigator_id"] = ids[0]
        locs = _lookup_module_ids(
            client,
            campaign_id=campaign_id,
            prefix=prefix,
            headers=headers,
            profile=profile,
            module="location",
            names=name_list("locations", "location"),
            cache=cache,
        )
        if locs:
            body["locations"] = locs
        date = normalize_iso_date(s("date")) or normalize_iso_date(session_date) or ""
        if date:
            body["date"] = date

    elif module == "event":
        locs = _lookup_module_ids(
            client,
            campaign_id=campaign_id,
            prefix=prefix,
            headers=headers,
            profile=profile,
            module="location",
            names=name_list("locations", "location"),
            cache=cache,
        )
        if locs:
            body["locations"] = locs
        date = normalize_iso_date(s("date")) or normalize_iso_date(session_date) or ""
        if date:
            body["date"] = date

    elif module == "item":
        loc = s("location") or (name_list("locations")[0] if name_list("locations") else "")
        if loc:
            ids = _lookup_module_ids(
                client,
                campaign_id=campaign_id,
                prefix=prefix,
                headers=headers,
                profile=profile,
                module="location",
                names=[loc],
                cache=cache,
            )
            if ids:
                body["location_id"] = ids[0]
        for key in ("price", "size", "weight"):
            if s(key):
                body[key] = s(key)
        creators = _lookup_entity_ids(
            client,
            campaign_id=campaign_id,
            prefix=prefix,
            headers=headers,
            profile=profile,
            module="character",
            names=name_list("creators", "creator"),
            cache=cache,
        )
        if creators:
            body["creators"] = creators

    elif module in {"family", "race", "note"}:
        pass

    return body


def _apply_entity_metadata(
    client: httpx.Client,
    *,
    campaign_id: int,
    prefix: str,
    headers: dict,
    profile: str,
    matched: EntityRef,
    fields: dict,
    session_date: str = "",
    cache: dict,
) -> dict:
    """PATCH module record with resolved metadata. Returns applied body (or {})."""
    body = _build_metadata_payload(
        client,
        campaign_id=campaign_id,
        prefix=prefix,
        headers=headers,
        profile=profile,
        module=matched.module,
        fields=fields,
        session_date=session_date,
        cache=cache,
    )
    if not body:
        return {}
    collection = module_path(profile, matched.module)
    if not collection:
        return {}
    # Merge location arrays with existing values when possible
    try:
        current = _request_with_retry(
            client.get,
            f"{prefix}/campaigns/{campaign_id}/{collection}/{matched.module_id}",
            headers=headers,
        )
        if current.status_code < 400:
            data = current.json().get("data") or {}
            for key in ("locations", "races", "families"):
                if key in body and isinstance(data.get(key), list):
                    existing = [
                        int(x) if not isinstance(x, dict) else int(x.get("id", 0))
                        for x in data[key]
                    ]
                    existing = [x for x in existing if x]
                    body[key] = sorted(set(existing) | set(body[key]))
            # Skip overwriting non-empty scalar metadata with nothing new
            for key in ("title", "age", "sex", "pronouns", "type", "date"):
                if key in body and data.get(key) and not fields.get(key) and key != "date":
                    # keep LLM value; if both exist prefer LLM when provided
                    pass
            # Don't clobber existing appearance/personality traits if already set
            if data.get("traits") and (
                "appearance_name" in body or "personality_name" in body
            ):
                body.pop("appearance_name", None)
                body.pop("appearance_entry", None)
                body.pop("personality_name", None)
                body.pop("personality_entry", None)
    except httpx.HTTPError:
        pass
    if not body:
        return {}
    response = _request_with_retry(
        client.patch,
        f"{prefix}/campaigns/{campaign_id}/{collection}/{matched.module_id}",
        headers=headers,
        json=body,
    )
    if response.status_code >= 400:
        # Retry without trait arrays if CE rejects them
        for key in (
            "appearance_name",
            "appearance_entry",
            "personality_name",
            "personality_entry",
        ):
            body.pop(key, None)
        if not body:
            return {}
        response = _request_with_retry(
            client.patch,
            f"{prefix}/campaigns/{campaign_id}/{collection}/{matched.module_id}",
            headers=headers,
            json=body,
        )
    response.raise_for_status()
    return body


def _unique_refs(refs: list[EntityRef]) -> list[EntityRef]:
    return list({ref.entity_id: ref for ref in refs}.values())


def _resolve_ref_list(refs: list[EntityRef]) -> tuple[EntityRef | None, bool]:
    """Return (match, ambiguous). Prefers a unique Player Character on ties."""
    unique = _unique_refs(refs)
    if not unique:
        return None, False
    if len(unique) == 1:
        return unique[0], False
    preferred = _prefer_unique_pc(unique)
    if preferred is not None:
        return preferred, False
    return None, True


def _find_match(
    candidate: EntityCandidate,
    refs: list[EntityRef],
    names: dict[str, list[EntityRef]],
    aliases: dict[str, list[EntityRef]],
) -> tuple[EntityRef | None, bool]:
    normalized = normalize_name(candidate.name)
    exact = names.get(normalized, [])
    if exact:
        return _resolve_ref_list(exact)

    exact_aliases = aliases.get(normalized, [])
    if exact_aliases:
        return _resolve_ref_list(exact_aliases)

    for candidate_alias in candidate.aliases:
        normalized_alias = normalize_name(candidate_alias)
        alias_name_matches = names.get(normalized_alias, [])
        if alias_name_matches:
            return _resolve_ref_list(alias_name_matches)
        alias_alias_matches = aliases.get(normalized_alias, [])
        if alias_alias_matches:
            return _resolve_ref_list(alias_alias_matches)

    fuzzy: list[EntityRef] = []
    for ref in refs:
        labels = [normalize_name(ref.name)]
        labels.extend(
            alias
            for alias, alias_refs in aliases.items()
            if any(item.entity_id == ref.entity_id for item in alias_refs)
        )
        if any(
            SequenceMatcher(None, normalized, label).ratio() >= 0.92
            for label in labels
        ):
            fuzzy.append(ref)
    return _resolve_ref_list(fuzzy)


def _build_module_index(
    client: httpx.Client,
    *,
    campaign_id: int,
    prefix: str,
    headers: dict,
    profile: str,
    module: str,
    alias_type: int,
    cache: dict,
) -> tuple[list[EntityRef], dict[str, list[EntityRef]], dict[str, list[EntityRef]]]:
    if module in cache:
        return cache[module]
    collection = module_path(profile, module)
    if not collection:
        raise KeyError(module)
    records = _get_pages(
        client,
        f"{prefix}/campaigns/{campaign_id}/{collection}",
        headers,
    )
    refs = [_entity_ref(module, record) for record in records]
    names: dict[str, list[EntityRef]] = {}
    aliases: dict[str, list[EntityRef]] = {}
    for ref in refs:
        names.setdefault(normalize_name(ref.name), []).append(ref)
        asset_records = _get_pages(
            client,
            (
                f"{prefix}/campaigns/{campaign_id}/entities/"
                f"{ref.entity_id}/entity_assets"
            ),
            headers,
        )
        for asset in asset_records:
            if int(asset.get("type_id", 0)) != alias_type:
                continue
            aliases.setdefault(normalize_name(asset["name"]), []).append(ref)
    cache[module] = refs, names, aliases
    return cache[module]


def _entity_has_post(
    client: httpx.Client,
    *,
    campaign_id: int,
    prefix: str,
    headers: dict,
    entity_id: int,
    post_name: str,
) -> bool:
    try:
        posts = _get_pages(
            client,
            f"{prefix}/campaigns/{campaign_id}/entities/{entity_id}/posts",
            headers,
        )
    except httpx.HTTPError:
        return False
    target = (post_name or "").strip().casefold()
    return any(str(p.get("name") or "").strip().casefold() == target for p in posts)


def sync_entities(
    client: httpx.Client,
    campaign_id: int,
    token: str,
    session_title: str,
    candidates: list[EntityCandidate],
    *,
    api_prefix: str = "/1.0",
    prior_touches: list[dict] | None = None,
    profile: str = "ce",
    write_posts: bool = True,
    create_missing: bool = True,
    campaign_slug: str = "",
    session_date: str = "",
) -> SyncResult:
    """Match-or-create entities (additive). Optionally append a session post.

    write_posts=False → Phase A stubs only (create/match + aliases).
    create_missing=False → Phase B posts only for already-known entities.
    """
    result = SyncResult()
    prefix = "/" + api_prefix.strip("/")
    headers = _headers(token)
    modules = load_profile(profile).get("modules", {})
    alias_type = alias_asset_type_id(profile)
    vis_all = visibility_id(profile, "all")
    vis_admin = visibility_id(profile, "admin")
    touched_ids = {
        int(touch["entity_id"])
        for touch in (prior_touches or [])
        if touch.get("entity_id") is not None
    }
    indexes: dict = {}
    iso_date = normalize_iso_date(session_date) or ""
    calendar_stamp = _calendar_stamp_for_posts(
        client,
        campaign_id=campaign_id,
        prefix=prefix,
        headers=headers,
        iso_date=iso_date,
    )

    for candidate in candidates:
        module = candidate.type.strip().lower()
        if module not in modules:
            result.errors.append(
                f"{candidate.name}: unknown entity type {candidate.type!r}"
            )
            continue
        try:
            refs, names, aliases = _build_module_index(
                client,
                campaign_id=campaign_id,
                prefix=prefix,
                headers=headers,
                profile=profile,
                module=module,
                alias_type=alias_type,
                cache=indexes,
            )
            matched, ambiguous = _find_match(candidate, refs, names, aliases)
            created = matched is None
            if created:
                if not create_missing:
                    result.errors.append(
                        f"{candidate.name}: no match for post-only sync"
                    )
                    continue
                if ambiguous:
                    result.errors.append(
                        f"{candidate.name}: ambiguous match — skipped create"
                    )
                    continue
                is_private = candidate.confidence not in {"high", "medium"}
                collection = module_path(profile, module)
                create_body: dict = {
                    "name": candidate.name,
                    "entry": html_entry(
                        candidate.summary,
                        candidate.evidence,
                        campaign_id=campaign_id,
                        campaign_slug=campaign_slug,
                    ),
                    "is_private": is_private,
                }
                if iso_date and module in {"event", "quest", "journal"}:
                    create_body["date"] = iso_date
                create_body.update(
                    _build_metadata_payload(
                        client,
                        campaign_id=campaign_id,
                        prefix=prefix,
                        headers=headers,
                        profile=profile,
                        module=module,
                        fields=candidate.fields,
                        session_date=iso_date,
                        cache=indexes,
                    )
                )
                response = _request_with_retry(
                    client.post,
                    f"{prefix}/campaigns/{campaign_id}/{collection}",
                    headers=headers,
                    json=create_body,
                )
                response.raise_for_status()
                matched = _entity_ref(module, response.json()["data"])
                refs.append(matched)
                names.setdefault(normalize_name(matched.name), []).append(matched)

            # Fill / refresh typed metadata on match or after create
            if candidate.fields or (
                iso_date and module in {"event", "quest", "journal"}
            ):
                try:
                    applied = _apply_entity_metadata(
                        client,
                        campaign_id=campaign_id,
                        prefix=prefix,
                        headers=headers,
                        profile=profile,
                        matched=matched,
                        fields=candidate.fields
                        or ({"date": iso_date} if iso_date else {}),
                        session_date=iso_date,
                        cache=indexes,
                    )
                    if applied:
                        # invalidate name indexes that might gain locations etc.
                        pass
                except Exception as meta_exc:  # noqa: BLE001
                    result.errors.append(
                        f"{candidate.name}: metadata {meta_exc}"
                    )

            for alias_name in candidate.aliases:
                alias_name = alias_name.strip()[:45]
                normalized_alias = normalize_name(alias_name)
                if not normalized_alias or normalized_alias == normalize_name(
                    matched.name
                ):
                    continue
                existing_refs = aliases.get(normalized_alias, [])
                if any(ref.entity_id == matched.entity_id for ref in existing_refs):
                    continue
                alias_response = _request_with_retry(
                    client.post,
                    (
                        f"{prefix}/campaigns/{campaign_id}/entities/"
                        f"{matched.entity_id}/entity_assets"
                    ),
                    headers=headers,
                    json={
                        "name": alias_name,
                        "type_id": alias_type,
                        "visibility_id": (
                            vis_admin if matched.is_private else vis_all
                        ),
                    },
                )
                alias_response.raise_for_status()
                aliases.setdefault(normalized_alias, []).append(matched)

            record = asdict(matched)
            if write_posts:
                if matched.entity_id in touched_ids:
                    (result.updated if not created else result.created).append(record)
                    continue
                if _entity_has_post(
                    client,
                    campaign_id=campaign_id,
                    prefix=prefix,
                    headers=headers,
                    entity_id=matched.entity_id,
                    post_name=session_title,
                ):
                    result.updated.append(record)
                    touched_ids.add(matched.entity_id)
                    continue
                post_body: dict = {
                    "name": session_title,
                    "entry": html_entry(
                        candidate.summary,
                        candidate.evidence,
                        campaign_id=campaign_id,
                        campaign_slug=campaign_slug,
                    ),
                    "visibility_id": (
                        vis_admin if candidate.confidence == "low" else vis_all
                    ),
                }
                if calendar_stamp:
                    post_body.update(calendar_stamp)
                post_response = _request_with_retry(
                    client.post,
                    (
                        f"{prefix}/campaigns/{campaign_id}/entities/"
                        f"{matched.entity_id}/posts"
                    ),
                    headers=headers,
                    json=post_body,
                )
                post_response.raise_for_status()
                record["post_id"] = int(post_response.json()["data"]["id"])
                touched_ids.add(matched.entity_id)

            (result.created if created else result.updated).append(record)
        except Exception as exc:
            result.errors.append(f"{candidate.name}: {exc}")

    return result


def link_organisation_members(
    client: httpx.Client,
    campaign_id: int,
    token: str,
    memberships: list[dict],
    *,
    api_prefix: str = "/1.0",
    profile: str = "ce",
    create_missing_orgs: bool = True,
) -> dict:
    """memberships: [{character, organisation, role?}]. Additive; skip existing links."""
    prefix = "/" + api_prefix.strip("/")
    headers = _headers(token)
    created: list[dict] = []
    skipped: list[str] = []
    errors: list[str] = []
    indexes: dict = {}
    alias_type = alias_asset_type_id(profile)

    def resolve(module: str, name: str) -> EntityRef | None:
        refs, names, aliases = _build_module_index(
            client,
            campaign_id=campaign_id,
            prefix=prefix,
            headers=headers,
            profile=profile,
            module=module,
            alias_type=alias_type,
            cache=indexes,
        )
        cand = EntityCandidate(type=module, name=name, confidence="high")
        matched, ambiguous = _find_match(cand, refs, names, aliases)
        if ambiguous:
            return None
        return matched

    def ensure_org(name: str) -> EntityRef | None:
        existing = resolve("organisation", name)
        if existing is not None:
            return existing
        if not create_missing_orgs:
            return None
        collection = module_path(profile, "organisation")
        if not collection:
            return None
        response = _request_with_retry(
            client.post,
            f"{prefix}/campaigns/{campaign_id}/{collection}",
            headers=headers,
            json={
                "name": name,
                "type": "Military" if "sentinel" in name.casefold() else "",
                "entry": f"<p>{escape(name)}</p>",
                "is_private": False,
            },
        )
        if response.status_code >= 400:
            return None
        ref = _entity_ref("organisation", response.json()["data"])
        # bust organisation name cache
        indexes.pop("nameindex:organisation", None)
        indexes.pop("entityindex:organisation", None)
        indexes.pop("organisation", None)
        return ref

    for item in memberships:
        char_name = str(item.get("character") or "").strip()
        org_name = str(item.get("organisation") or item.get("organization") or "").strip()
        role = str(item.get("role") or "member").strip()[:45] or "member"
        if not char_name or not org_name:
            continue
        # Normalize "the Sentinels" → "Sentinels"
        if org_name.casefold().startswith("the "):
            org_name = org_name[4:].strip() or org_name
        try:
            char = resolve("character", char_name)
            org = ensure_org(org_name)
            if char is None or org is None:
                errors.append(f"{char_name}∈{org_name}: unresolved character/org")
                continue
            members = _get_pages(
                client,
                (
                    f"{prefix}/campaigns/{campaign_id}/organisations/"
                    f"{org.module_id}/organisation_members"
                ),
                headers,
            )
            if any(int(m.get("character_id", 0)) == char.module_id for m in members):
                skipped.append(f"{char_name} already in {org_name}")
                continue
            response = _request_with_retry(
                client.post,
                (
                    f"{prefix}/campaigns/{campaign_id}/organisations/"
                    f"{org.module_id}/organisation_members"
                ),
                headers=headers,
                json={
                    "organisation_id": org.module_id,
                    "character_id": char.module_id,
                    "role": role,
                    "status_id": 0,
                    "is_private": False,
                },
            )
            response.raise_for_status()
            created.append(
                {
                    "character": char_name,
                    "organisation": org_name,
                    "role": role,
                    "id": response.json()["data"].get("id"),
                }
            )
        except Exception as exc:
            errors.append(f"{char_name}∈{org_name}: {exc}")
    return {"created": created, "skipped": skipped, "errors": errors}


SESSION_TIMELINE_NAME = "Session Chronicle"


def ensure_session_timeline_element(
    client: httpx.Client,
    campaign_id: int,
    token: str,
    *,
    session_title: str,
    summary_html: str,
    journal_entity_id: int | None = None,
    session_date: str = "",
    api_prefix: str = "/1.0",
    profile: str = "ce",
) -> dict:
    """Ensure Session Chronicle timeline + era; add one element per session title."""
    prefix = "/" + api_prefix.strip("/")
    headers = _headers(token)
    timelines = _get_pages(
        client, f"{prefix}/campaigns/{campaign_id}/timelines", headers
    )
    timeline = next(
        (
            t
            for t in timelines
            if str(t.get("name") or "").strip().casefold()
            == SESSION_TIMELINE_NAME.casefold()
        ),
        None,
    )
    if timeline is None:
        response = _request_with_retry(
            client.post,
            f"{prefix}/campaigns/{campaign_id}/timelines",
            headers=headers,
            json={
                "name": SESSION_TIMELINE_NAME,
                "entry": "<p>Auto-maintained chronicle of play sessions.</p>",
                "type": "Sessions",
                "is_private": False,
            },
        )
        response.raise_for_status()
        timeline = response.json()["data"]
    timeline_id = int(timeline["id"])

    eras = _get_pages(
        client,
        f"{prefix}/campaigns/{campaign_id}/timelines/{timeline_id}/timeline_eras",
        headers,
    )
    if not eras:
        era_resp = _request_with_retry(
            client.post,
            f"{prefix}/campaigns/{campaign_id}/timelines/{timeline_id}/timeline_eras",
            headers=headers,
            json={"name": "Campaign Era", "abbreviation": "CE", "position": 1},
        )
        era_resp.raise_for_status()
        era_id = int(era_resp.json()["data"]["id"])
    else:
        era_id = int(eras[0]["id"])

    elements = _get_pages(
        client,
        f"{prefix}/campaigns/{campaign_id}/timelines/{timeline_id}/timeline_elements",
        headers,
    )
    title = (session_title or "Session").strip()
    existing = next(
        (
            e
            for e in elements
            if str(e.get("name") or "").strip().casefold() == title.casefold()
        ),
        None,
    )
    if existing:
        return {
            "timeline_id": timeline_id,
            "era_id": era_id,
            "element_id": int(existing["id"]),
            "created": False,
        }

    body: dict = {
        "name": title,
        "era_id": era_id,
        "entry": summary_html or f"<p>{escape(title)}</p>",
        "visibility_id": visibility_id(profile, "all"),
    }
    normalized_date = normalize_iso_date(session_date) or ""
    if normalized_date:
        body["date"] = normalized_date
    if journal_entity_id:
        body["entity_id"] = int(journal_entity_id)
    el_resp = _request_with_retry(
        client.post,
        f"{prefix}/campaigns/{campaign_id}/timelines/{timeline_id}/timeline_elements",
        headers=headers,
        json=body,
    )
    el_resp.raise_for_status()
    return {
        "timeline_id": timeline_id,
        "era_id": era_id,
        "element_id": int(el_resp.json()["data"]["id"]),
        "created": True,
    }


def _ensure_real_world_calendar(
    client: httpx.Client,
    *,
    campaign_id: int,
    prefix: str,
    headers: dict,
    iso_date: str = "",
) -> int | None:
    """Return a calendar id, creating a Gregorian 'Real World' calendar if needed."""
    calendars = _get_pages(
        client, f"{prefix}/campaigns/{campaign_id}/calendars", headers
    )
    if calendars:
        return int(calendars[0]["id"])
    parts = (normalize_iso_date(iso_date) or "2025-01-01").split("-")
    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    body = {
        "name": "Real World",
        "type": "Gregorian",
        "current_year": year,
        "current_month": month,
        "current_day": day,
        "month_name": [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        "month_length": [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31],
        "month_type": ["standard"] * 12,
        "weekday": [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ],
        "has_leap_year": True,
        "leap_year_amount": 1,
        "leap_year_month": 2,
        "leap_year_offset": 1,
        "leap_year_start": 1,
        "skip_year_zero": False,
    }
    response = _request_with_retry(
        client.post,
        f"{prefix}/campaigns/{campaign_id}/calendars",
        headers=headers,
        json=body,
    )
    if response.status_code >= 400:
        return None
    return int(response.json()["data"]["id"])


def _calendar_stamp_for_posts(
    client: httpx.Client,
    *,
    campaign_id: int,
    prefix: str,
    headers: dict,
    iso_date: str,
) -> dict:
    """Optional calendar_* fields for posts when a real-world date is known."""
    normalized = normalize_iso_date(iso_date) or ""
    if not normalized:
        return {}
    year_s, month_s, day_s = normalized.split("-")
    calendar_id = _ensure_real_world_calendar(
        client,
        campaign_id=campaign_id,
        prefix=prefix,
        headers=headers,
        iso_date=normalized,
    )
    if not calendar_id:
        return {}
    return {
        "calendar_id": calendar_id,
        "calendar_year": int(year_s),
        "calendar_month": int(month_s),
        "calendar_day": int(day_s),
        "calendar_reminder_length": 1,
    }


def ensure_journal_calendar_reminder(
    client: httpx.Client,
    campaign_id: int,
    token: str,
    *,
    journal_entity_id: int,
    iso_date: str,
    api_prefix: str = "/1.0",
) -> dict:
    """Attach a calendar reminder to the journal for the played-on date.

    iso_date: YYYY-MM-DD (or parseable). Creates a Real World calendar if none exist.
    """
    prefix = "/" + api_prefix.strip("/")
    headers = _headers(token)
    normalized = normalize_iso_date(iso_date) or ""
    parts = normalized.split("-") if normalized else []
    if len(parts) != 3:
        return {"created": False, "reason": "no_parseable_date"}
    year, month, day = (int(parts[0]), int(parts[1]), int(parts[2]))
    calendar_id = _ensure_real_world_calendar(
        client,
        campaign_id=campaign_id,
        prefix=prefix,
        headers=headers,
        iso_date=normalized,
    )
    if not calendar_id:
        return {"created": False, "reason": "no_calendar"}
    # Skip if a reminder with same y/m/d already exists (CE lists via /reminders)
    try:
        existing = _get_pages(
            client,
            f"{prefix}/campaigns/{campaign_id}/entities/{journal_entity_id}/reminders",
            headers,
        )
        for ev in existing:
            if (
                int(ev.get("calendar_id", 0)) == calendar_id
                and int(ev.get("year", -1)) == year
                and int(ev.get("month", -1)) == month
                and int(ev.get("day", -1)) == day
            ):
                return {"created": False, "reason": "already_exists", "id": ev.get("id")}
    except httpx.HTTPError:
        pass
    reminder_body = {
        "name": "Session date",
        "calendar_id": calendar_id,
        "year": year,
        "month": month,
        "day": day,
        "length": 1,
        "visibility_id": 1,
        "comment": "Session played date",
    }
    response = _request_with_retry(
        client.post,
        f"{prefix}/campaigns/{campaign_id}/entities/{journal_entity_id}/reminders",
        headers=headers,
        json=reminder_body,
    )
    if response.status_code == 404:
        response = _request_with_retry(
            client.post,
            f"{prefix}/campaigns/{campaign_id}/entities/{journal_entity_id}/entity_events",
            headers=headers,
            json=reminder_body,
        )
    if response.status_code >= 400:
        return {
            "created": False,
            "reason": f"reminder_http_{response.status_code}",
            "calendar_id": calendar_id,
            "detail": (response.text or "")[:300],
        }
    return {
        "created": True,
        "id": response.json()["data"].get("id"),
        "calendar_id": calendar_id,
    }
