"""Deterministic speaker remapping and timestamp helpers for transcripts."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kanka_scribe.session_notes import SessionMeta

# Craig: **name:**rest   plain: Name: rest   bracket: [Name]: rest
_CRAIG_SPEAKER = re.compile(r"^(?P<pre>\s*)\*\*(?P<name>.+?):\*\*(?P<rest>.*)$")
_PLAIN_SPEAKER = re.compile(r"^(?P<pre>\s*)(?P<name>[^:\n\[\]]+?):(?P<rest>\s.*)?$")
_BRACKET_SPEAKER = re.compile(
    r"^(?P<pre>\s*)\[(?P<name>[^\]]+)\]:(?P<rest>\s.*)?$"
)

# [00:01:02], [0:01:02], 00:01:02, (01:02:03)
_TIMESTAMP = re.compile(
    r"(?:\[|\()?(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})(?:\]|\))?"
)


def _norm_label(value: str) -> str:
    text = (value or "").strip().casefold()
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def build_speaker_map(cast: list[dict]) -> dict[str, str]:
    """Map normalized speaker/alias labels → canonical character name."""
    mapping: dict[str, str] = {}
    for ch in cast:
        name = str(ch.get("name") or "").strip()
        if not name:
            continue
        mapping[_norm_label(name)] = name
        for alias in ch.get("aliases") or []:
            label = str(alias or "").strip()
            if label:
                mapping[_norm_label(label)] = name
    return mapping


def remap_speakers(transcript: str, cast: list[dict]) -> str:
    """Rewrite known speaker labels to character names; leave unknowns alone."""
    if not transcript:
        return transcript
    mapping = build_speaker_map(cast)
    if not mapping:
        return transcript

    lines_out: list[str] = []
    for line in transcript.splitlines():
        craig = _CRAIG_SPEAKER.match(line)
        if craig:
            raw = craig.group("name").strip()
            canon = mapping.get(_norm_label(raw))
            if canon:
                lines_out.append(
                    f"{craig.group('pre')}**{canon}:**{craig.group('rest')}"
                )
                continue
            lines_out.append(line)
            continue

        bracket = _BRACKET_SPEAKER.match(line)
        if bracket:
            raw = bracket.group("name").strip()
            canon = mapping.get(_norm_label(raw))
            if canon:
                rest = bracket.group("rest") or ""
                lines_out.append(f"{bracket.group('pre')}[{canon}]:{rest}")
                continue
            lines_out.append(line)
            continue

        plain = _PLAIN_SPEAKER.match(line)
        if plain:
            raw = plain.group("name").strip()
            # Skip lines that look like timestamps mistaken as speakers
            if re.fullmatch(r"\d{1,2}", raw):
                lines_out.append(line)
                continue
            canon = mapping.get(_norm_label(raw))
            if canon:
                rest = plain.group("rest") or ""
                if rest.startswith(" "):
                    lines_out.append(f"{plain.group('pre')}{canon}:{rest}")
                elif rest:
                    lines_out.append(f"{plain.group('pre')}{canon}: {rest.lstrip()}")
                else:
                    lines_out.append(f"{plain.group('pre')}{canon}:")
                continue
            lines_out.append(line)
            continue

        lines_out.append(line)
    return "\n".join(lines_out)


def _hms_to_seconds(h: str, m: str, s: str) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def extract_timestamps(text: str) -> list[int]:
    """Return timestamps found in text as seconds from start (order preserved)."""
    out: list[int] = []
    for match in _TIMESTAMP.finditer(text or ""):
        out.append(_hms_to_seconds(match.group("h"), match.group("m"), match.group("s")))
    return out


def seconds_to_hms(total: int) -> str:
    total = max(0, int(total))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}h")
    if m or h:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


def apply_timing_to_meta(meta: "SessionMeta", text: str) -> "SessionMeta":
    """Set start/end/duration on meta from earliest/latest timestamps in text."""
    stamps = extract_timestamps(text)
    if not stamps:
        meta.start = "Unknown"
        meta.end = "Unknown"
        meta.duration = "Unknown"
        return meta
    first, last = stamps[0], stamps[-1]
    meta.start = seconds_to_hms(first)
    meta.end = seconds_to_hms(last)
    meta.duration = format_duration(last - first) if last >= first else "Unknown"
    if meta.time == "Unknown":
        meta.time = meta.start
    return meta
