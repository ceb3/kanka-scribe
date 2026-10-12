"""Deterministic entity candidates from Goblin Scribe recap header lists."""

from __future__ import annotations

import re

from kanka_scribe.entity_extract import EntityCandidate

_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HEADER = re.compile(
    r"^\*\*(?P<label>[^*]+):\*\*\s*(?P<body>.+)$",
    re.I,
)

# Map recap labels → Kanka module types
_LABEL_TYPES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^participants?$", re.I), "character"),
    (re.compile(r"^locations?$", re.I), "location"),
    (re.compile(r"^quests?(?:\s*/\s*objectives?)?$", re.I), "quest"),
    (re.compile(r"^npcs?$", re.I), "character"),
    (re.compile(r"^items?(?:\s*&\s*discoveries?)?$", re.I), "item"),
    (re.compile(r"^discoveries$", re.I), "item"),
    (re.compile(r"^organisations?|organizations?|factions?$", re.I), "organisation"),
    (re.compile(r"^events?$", re.I), "event"),
    (re.compile(r"^creatures?|monsters?$", re.I), "creature"),
]


def _strip_links(text: str) -> str:
    return _MD_LINK.sub(r"\1", text)


def _split_names(body: str) -> list[str]:
    body = _strip_links(body).strip()
    if not body or body.casefold() in {"unknown", "none", "n/a", "-"}:
        return []
    # Comma / semicolon / bullet / pipe — do NOT split on "and" (breaks quest phrases)
    parts = re.split(r"\s*[,;•|]\s+", body)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        name = part.strip(" .-–—*")
        # Drop trailing parenthetical role notes for NPCs: "Donovan (lieutenant)"
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        if not name or len(name) < 2:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _label_type(label: str) -> str | None:
    cleaned = label.strip().rstrip(":")
    for pattern, module in _LABEL_TYPES:
        if pattern.match(cleaned):
            return module
    return None


def candidates_from_cast(cast: list[dict]) -> list[EntityCandidate]:
    """Phase A stubs for characters typed Player Character in Kanka only."""
    from kanka_scribe.kanka_entities import is_player_character_type

    out: list[EntityCandidate] = []
    seen: set[str] = set()
    for ch in cast or []:
        if not is_player_character_type(ch.get("character_type")):
            continue
        name = str(ch.get("name") or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        aliases = [
            str(a).strip()
            for a in (ch.get("aliases") or [])
            if str(a).strip() and str(a).strip().casefold() != key
        ]
        out.append(
            EntityCandidate(
                type="character",
                name=name,
                aliases=aliases,
                summary="Player character (campaign cast).",
                confidence="high",
                evidence=["cast list"],
                fields={"type": "Player Character"},
            )
        )
    return out


def candidates_from_recap(recap: str) -> list[EntityCandidate]:
    """Pull high-confidence candidates from structured recap header lines."""
    found: list[EntityCandidate] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in (recap or "").splitlines():
        line = raw_line.strip()
        match = _HEADER.match(line)
        if not match:
            continue
        module = _label_type(match.group("label"))
        if not module:
            continue
        for name in _split_names(match.group("body")):
            key = (module, name.casefold())
            if key in seen:
                continue
            seen.add(key)
            found.append(
                EntityCandidate(
                    type=module,
                    name=name,
                    aliases=[],
                    summary=f"Mentioned in session recap ({match.group('label').strip()}).",
                    confidence="high",
                    evidence=[line[:240]],
                )
            )
    return found
