"""Convert markdown (or pass through HTML) for Kanka TipTap entry fields."""

from __future__ import annotations

import re
from html import escape

import markdown as md

_HTML_BLOCK = re.compile(
    r"^\s*<(?:p|div|h[1-6]|ul|ol|table|blockquote|pre|hr)\b",
    re.I,
)
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")
_OUTER_P = re.compile(r"^<p>(.*?)</p>\s*$", re.I | re.S)


def _prep_markdown(text: str) -> str:
    """Insert blank lines so CommonMark lists parse after bold labels."""
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        if (
            out
            and _LIST_ITEM.match(line)
            and out[-1].strip()
            and not _LIST_ITEM.match(out[-1])
        ):
            out.append("")
        out.append(line)
    return "\n".join(out)


def rewrite_campaign_links(
    text: str,
    *,
    campaign_id: int | None = None,
    campaign_slug: str = "",
) -> str:
    """Rewrite /w/{campaign_id}/… to /w/{slug}/… when a public slug is known."""
    raw = text or ""
    slug = (campaign_slug or "").strip()
    if not raw or not slug or campaign_id is None:
        return raw
    return re.sub(rf"/w/{re.escape(str(campaign_id))}/", f"/w/{slug}/", raw)


def markdown_to_kanka_html(
    text: str,
    *,
    campaign_id: int | None = None,
    campaign_slug: str = "",
) -> str:
    """Return HTML suitable for Kanka-CE TipTap / HTMLPurifier entry fields.

    Plain markdown from Ollama is converted. Content that already looks like
    an HTML block document is returned unchanged (entity sync already emits HTML).
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    if _HTML_BLOCK.match(raw):
        html = raw
    else:
        html = md.markdown(
            _prep_markdown(raw),
            extensions=["extra", "sane_lists", "nl2br"],
            output_format="html",
        )
    return rewrite_campaign_links(
        html, campaign_id=campaign_id, campaign_slug=campaign_slug
    )


def markdown_fragment_to_html(
    text: str,
    *,
    campaign_id: int | None = None,
    campaign_slug: str = "",
) -> str:
    """Convert a one-line markdown fragment (for <li> bodies); unwrap a sole <p>."""
    raw = (text or "").strip()
    if not raw:
        return ""
    html = markdown_to_kanka_html(
        raw, campaign_id=campaign_id, campaign_slug=campaign_slug
    )
    match = _OUTER_P.match(html)
    if match and "<p" not in match.group(1).lower():
        return match.group(1)
    return html or escape(raw)


def html_entry(
    summary: str,
    evidence: list[str],
    *,
    campaign_id: int | None = None,
    campaign_slug: str = "",
) -> str:
    """Build a Kanka entry from summary + evidence with real HTML (not raw markdown)."""
    summary_html = markdown_to_kanka_html(
        summary or "", campaign_id=campaign_id, campaign_slug=campaign_slug
    )
    if not summary_html and (summary or "").strip():
        summary_html = f"<p>{escape(summary.strip())}</p>"
    parts: list[str] = []
    if summary_html:
        parts.append(summary_html)
    items = [
        markdown_fragment_to_html(
            item, campaign_id=campaign_id, campaign_slug=campaign_slug
        )
        for item in evidence
        if str(item or "").strip()
    ]
    items = [item for item in items if item]
    if items:
        parts.append("<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>")
    return "".join(parts)
