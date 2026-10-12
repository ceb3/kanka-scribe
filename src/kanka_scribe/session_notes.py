"""Session journal / transcript note formatting helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from kanka_scribe.discord_notify import linkify_recap

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I | re.M)


@dataclass
class SessionMeta:
    session: str = "Unknown"
    date: str = "Unknown"
    time: str = "Unknown"
    start: str = "Unknown"
    end: str = "Unknown"
    duration: str = "Unknown"
    participants: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)


def _clean_label(value: object, default: str = "Unknown") -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"null", "none", "n/a", "unknown", "?"}:
        return default
    return text


def _clean_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        name = str(item or "").strip()
        if not name or name.lower() in {"unknown", "null", "none"}:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def parse_session_meta(content: str) -> SessionMeta:
    """Parse LLM JSON into SessionMeta; unknowns on failure."""
    text = _FENCE.sub("", (content or "").strip()).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return SessionMeta()
    if not isinstance(data, dict):
        return SessionMeta()
    return SessionMeta(
        session=_clean_label(data.get("session")),
        date=_clean_label(data.get("date")),
        time=_clean_label(data.get("time")),
        participants=_clean_list(data.get("participants")),
        locations=_clean_list(data.get("locations")),
    )


def _fmt_linked_list(names: list[str], name_to_url: dict[str, str]) -> str:
    if not names:
        return "Unknown"
    parts: list[str] = []
    for name in names:
        url = ""
        for key, candidate in name_to_url.items():
            if key.casefold() == name.casefold():
                url = candidate
                break
        parts.append(f"[{name}]({url})" if url else name)
    return ", ".join(parts)


def build_transcript_header(
    meta: SessionMeta,
    *,
    source: str = "",
    name_to_url: dict[str, str] | None = None,
) -> str:
    urls = name_to_url or {}
    lines = [
        f"**Session:** {_clean_label(meta.session)}",
        f"**Date:** {_clean_label(meta.date)}",
        f"**Time:** {_clean_label(meta.time)}",
        f"**Start:** {_clean_label(meta.start)}",
        f"**End:** {_clean_label(meta.end)}",
        f"**Duration:** {_clean_label(meta.duration)}",
        f"**Participants:** {_fmt_linked_list(meta.participants, urls)}",
        f"**Locations:** {_fmt_linked_list(meta.locations, urls)}",
    ]
    src = (source or "").strip() or "Unknown"
    lines.append(f"**Source:** {src}")
    return "\n".join(lines)


def build_transcript_note(
    *,
    transcript: str,
    meta: SessionMeta,
    source: str = "",
    name_to_url: dict[str, str] | None = None,
    archive_id: str | None = None,
) -> str:
    body = (transcript or "").rstrip()
    header = build_transcript_header(meta, source=source, name_to_url=name_to_url)
    # Linkify names that appear in the header labels only (already linked);
    # leave transcript body untouched except archive footer.
    parts = [header, "", "---", "", body]
    note = "\n".join(parts)
    if archive_id:
        note = f"{note.rstrip()}\n\n---\nSource archive: `{archive_id}`\n"
    return note


_ISO_DATE = re.compile(r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})")
_US_DATE = re.compile(r"(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})")
_MONTH_NAME = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_NAMED_DATE = re.compile(
    r"(?P<month>january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})",
    re.I,
)
_NAMED_DATE_DMY = re.compile(
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(?P<month>january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r",?\s+(?P<year>\d{4})",
    re.I,
)
_DATE_PLAYED_LINE = re.compile(
    r"(?i)(?:date\s*played|session\s*date|\*\*date\*\*|date)\s*[:\-]\s*(.+)$"
)


def normalize_iso_date(value: str) -> str | None:
    """Return YYYY-MM-DD if value looks like a real calendar date, else None."""
    text = (value or "").strip()
    if not text or text.casefold() in {"unknown", "none", "n/a", "null", "?"}:
        return None
    match = _ISO_DATE.search(text)
    if match:
        y, m, d = int(match.group("y")), int(match.group("m")), int(match.group("d"))
        if 1 <= m <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
            return f"{y:04d}-{m:02d}-{d:02d}"
    match = _NAMED_DATE.search(text)
    if match:
        month = _MONTH_NAME[match.group("month").casefold()]
        y, d = int(match.group("year")), int(match.group("day"))
        if 1 <= d <= 31 and 1900 <= y <= 2100:
            return f"{y:04d}-{month:02d}-{d:02d}"
    match = _NAMED_DATE_DMY.search(text)
    if match:
        month = _MONTH_NAME[match.group("month").casefold()]
        y, d = int(match.group("year")), int(match.group("day"))
        if 1 <= d <= 31 and 1900 <= y <= 2100:
            return f"{y:04d}-{month:02d}-{d:02d}"
    match = _US_DATE.search(text)
    if match:
        y, m, d = int(match.group("y")), int(match.group("m")), int(match.group("d"))
        if 1 <= m <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
            return f"{y:04d}-{m:02d}-{d:02d}"
    return None


def parse_date_from_text(*texts: str) -> str | None:
    """Scan title/recap/transcript snippets for a played-on date."""
    for text in texts:
        if not text:
            continue
        for line in text.splitlines():
            label = _DATE_PLAYED_LINE.search(line.strip())
            if label:
                found = normalize_iso_date(label.group(1))
                if found:
                    return found
        found = normalize_iso_date(text)
        if found:
            return found
    return None


def enrich_meta_from_title(meta: SessionMeta, title: str) -> SessionMeta:
    """Prefer Craig-style title date when meta.date is unknown."""
    if meta.date != "Unknown":
        normalized = normalize_iso_date(meta.date)
        if normalized:
            meta.date = normalized
            return meta
    found = parse_date_from_text(title or "")
    if found:
        meta.date = found
    return meta


def enrich_meta_from_recap(meta: SessionMeta, recap: str) -> SessionMeta:
    """Pull Date Played / session date from Notion-style recap headers."""
    if meta.date != "Unknown":
        normalized = normalize_iso_date(meta.date)
        if normalized:
            meta.date = normalized
            return meta
    found = parse_date_from_text(recap or "")
    if found:
        meta.date = found
    # Session number from recap when LLM left it Unknown
    if meta.session == "Unknown" and recap:
        clean = re.sub(r"[*_`]", "", recap)
        match = re.search(
            r"(?i)session\s*(?:number|#)?\s*[:\-]?\s*(\d{1,4})\b", clean
        )
        if match:
            meta.session = match.group(1)
    return meta


def enrich_meta_from_cast(
    meta: SessionMeta,
    cast: list[dict],
    recap: str,
) -> SessionMeta:
    """If participants empty, fill from cast names mentioned in the recap."""
    if meta.participants:
        return meta
    text = recap or ""
    found: list[str] = []
    for ch in cast:
        name = str(ch.get("name") or "").strip()
        if not name:
            continue
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I):
            found.append(name)
    if found:
        meta.participants = found
    return meta


def linkify_document(text: str, name_to_url: dict[str, str]) -> str:
    """Linkify entity names in a markdown document (journal recap)."""
    return linkify_recap(text, name_to_url)
