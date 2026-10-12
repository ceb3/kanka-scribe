from __future__ import annotations

import re
from dataclasses import dataclass, field

from kanka_scribe.entity_types import CONFIDENCE_RANK

_ARTICLE = re.compile(r"^(a|an|the)\s+", re.I)
_NON_ALNUM = re.compile(r"[^\w\s]", re.UNICODE)
_SPEAKER_BLOCK = re.compile(r"^(\*\*[^:\n]+:\*\*)\s*\n?(.*)$", re.S)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_OVERLAP_CHARS = 240


@dataclass
class EntityCandidate:
    type: str
    name: str
    aliases: list[str] = field(default_factory=list)
    summary: str = ""
    confidence: str = "low"
    evidence: list[str] = field(default_factory=list)
    # Typed Kanka metadata (title, sex, locations names, appearance traits, …)
    fields: dict = field(default_factory=dict)


def normalize_name(name: str) -> str:
    s = name.strip().casefold()
    s = _ARTICLE.sub("", s)
    s = _NON_ALNUM.sub("", s)
    return " ".join(s.split())


def _is_article_leading(name: str) -> bool:
    return bool(_ARTICLE.match(name.strip()))


def _pick_display_name(names: list[str], name_confidence: dict[str, int]) -> str:
    unique: list[str] = []
    seen: set[str] = set()
    for n in names:
        n = n.strip()
        if not n:
            continue
        norm = normalize_name(n)
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(n)
    if not unique:
        return ""
    non_article = [n for n in unique if not _is_article_leading(n)]
    pool = non_article if non_article else unique
    return max(pool, key=lambda n: (name_confidence.get(n, 0), len(n)))


def _apply_display_name(cur: EntityCandidate, name_confidence: dict[str, int]) -> None:
    chosen = _pick_display_name([cur.name, *cur.aliases], name_confidence)
    if not chosen:
        return
    norms_seen: set[str] = set()
    aliases: list[str] = []
    for n in [cur.name, *cur.aliases]:
        n = n.strip()
        if not n or n == chosen:
            continue
        norm = normalize_name(n)
        if norm == normalize_name(chosen) or norm in norms_seen:
            continue
        norms_seen.add(norm)
        aliases.append(n)
    cur.name = chosen
    cur.aliases = aliases


def _split_text(text: str, limit: int) -> list[str]:
    pieces: list[str] = []
    for sentence in _SENTENCE_BOUNDARY.split(text.strip()):
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit + 1)
            if cut <= 0:
                cut = limit
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        if pieces and len(pieces[-1]) + 1 + len(sentence) <= limit:
            pieces[-1] += " " + sentence
        else:
            pieces.append(sentence)
    return pieces


def _split_oversized_block(block: str, target_chars: int) -> list[str]:
    if len(block) <= target_chars:
        return [block]
    match = _SPEAKER_BLOCK.match(block.strip())
    if not match:
        return _split_text(block, target_chars)
    header, body = match.groups()
    prefix = f"{header}\n"
    body_limit = max(1, target_chars - len(prefix))
    return [prefix + piece for piece in _split_text(body, body_limit)]


def _bounded_overlap(block: str) -> str:
    if len(block) <= _OVERLAP_CHARS:
        return block
    match = _SPEAKER_BLOCK.match(block.strip())
    if not match:
        return block[-_OVERLAP_CHARS:]
    header, body = match.groups()
    prefix = f"{header}\n"
    body_limit = max(1, _OVERLAP_CHARS - len(prefix))
    tail = body[-body_limit:]
    if len(body) > body_limit and " " in tail:
        tail = tail.split(" ", 1)[1]
    return prefix + tail


def chunk_transcript(transcript: str, context_length: int) -> list[str]:
    target_chars = max(500, (context_length // 2) * 4)
    raw_blocks = [b for b in transcript.split("\n\n") if b.strip()]
    blocks = [
        part
        for block in raw_blocks
        for part in _split_oversized_block(block, target_chars)
    ]
    if not blocks:
        return []
    chunks: list[str] = []
    parts: list[str] = []
    size = 0
    for block in blocks:
        add = len(block) + (2 if parts else 0)
        if parts and size + add > target_chars:
            chunks.append("\n\n".join(parts))
            overlap = _bounded_overlap(parts[-1])
            parts = [overlap] if overlap else []
            size = len(overlap)
            add = len(block) + (2 if parts else 0)
        parts.append(block)
        size += add
    if parts:
        chunks.append("\n\n".join(parts))
    return chunks


def merge_candidates(candidates: list[EntityCandidate]) -> list[EntityCandidate]:
    # Union-find style via canonical key per type
    groups: dict[tuple[str, str], EntityCandidate] = {}
    alias_index: dict[tuple[str, str], str] = {}  # (type, norm) -> canonical norm name
    name_confidence: dict[tuple[str, str], dict[str, int]] = {}

    def note_name(key: tuple[str, str], label: str, confidence: str) -> None:
        label = label.strip()
        if not label:
            return
        rank = CONFIDENCE_RANK.get(confidence, 0)
        per = name_confidence.setdefault(key, {})
        per[label] = max(per.get(label, 0), rank)

    def canonical_key(t: str, n: str) -> tuple[str, str]:
        norm = normalize_name(n)
        if (t, norm) in alias_index:
            return (t, alias_index[(t, norm)])
        return (t, norm)

    for raw in candidates:
        t = raw.type.strip().lower()
        if not raw.name.strip():
            continue
        key = canonical_key(t, raw.name)
        # If name matches an existing alias key, reuse
        for al in raw.aliases:
            ak = (t, normalize_name(al))
            if ak in alias_index:
                key = (t, alias_index[ak])
                break
            if ak in groups:
                key = ak
                break

        if key not in groups:
            groups[key] = EntityCandidate(
                type=t,
                name=raw.name.strip(),
                aliases=[],
                summary=raw.summary.strip(),
                confidence=raw.confidence if raw.confidence in CONFIDENCE_RANK else "low",
                evidence=[],
                fields=dict(raw.fields or {}),
            )
        cur = groups[key]
        conf = raw.confidence if raw.confidence in CONFIDENCE_RANK else "low"
        note_name(key, raw.name, conf)
        for al in raw.aliases:
            note_name(key, al, conf)
        if CONFIDENCE_RANK.get(conf, 0) > CONFIDENCE_RANK.get(cur.confidence, 0):
            cur.confidence = conf
        if normalize_name(raw.name) != normalize_name(cur.name):
            if raw.name.strip() not in cur.aliases:
                cur.aliases.append(raw.name.strip())
        for al in raw.aliases:
            al = al.strip()
            if al and normalize_name(al) != normalize_name(cur.name) and al not in cur.aliases:
                cur.aliases.append(al)
        if raw.summary.strip() and raw.summary.strip() not in cur.summary:
            # Prefer richer wiki prose over gluing thin stubs together.
            incoming = raw.summary.strip()
            if not cur.summary:
                cur.summary = incoming
            elif len(incoming) > len(cur.summary) + 40:
                cur.summary = incoming
            elif len(cur.summary) > len(incoming) + 40:
                pass
            else:
                cur.summary = (cur.summary + " " + incoming).strip()
        for ev in raw.evidence:
            if ev and ev not in cur.evidence:
                cur.evidence.append(ev)
        if raw.fields:
            cur.fields = _merge_fields(cur.fields, raw.fields)

        # refresh alias index
        canon = key[1]
        alias_index[(t, normalize_name(cur.name))] = canon
        for al in cur.aliases:
            alias_index[(t, normalize_name(al))] = canon

    for key, cur in groups.items():
        _apply_display_name(cur, name_confidence.get(key, {}))

    return list(groups.values())


def _merge_fields(base: dict, incoming: dict) -> dict:
    """Merge typed metadata; prefer non-empty incoming values; union name lists."""
    out = dict(base or {})
    for key, value in (incoming or {}).items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, list) and isinstance(out.get(key), list):
            seen = {json_safe(x) for x in out[key]}
            merged = list(out[key])
            for item in value:
                marker = json_safe(item)
                if marker not in seen:
                    merged.append(item)
                    seen.add(marker)
            out[key] = merged
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **value}
        else:
            # Prefer longer string / richer value when both present
            prior = out.get(key)
            if isinstance(value, str) and isinstance(prior, str):
                if len(value) >= len(prior):
                    out[key] = value
            else:
                out[key] = value
    return out


def json_safe(value: object) -> str:
    if isinstance(value, dict):
        return repr(sorted(value.items()))
    return str(value).casefold()
