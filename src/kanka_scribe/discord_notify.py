from __future__ import annotations

import re

import httpx

from kanka_scribe.kanka_campaign import public_campaign_ref


def entity_url(
    public_base: str,
    campaign_id: int,
    entity_id: int,
    *,
    campaign_slug: str = "",
) -> str:
    base = public_base.rstrip("/")
    campaign_ref = public_campaign_ref(
        campaign_id=campaign_id, campaign_slug=campaign_slug
    )
    return f"{base}/w/{campaign_ref}/entities/{entity_id}"


def build_name_to_url(
    *,
    public_base: str,
    campaign_id: int,
    cast: list[dict] | None = None,
    entities: list[dict] | None = None,
    campaign_slug: str = "",
) -> dict[str, str]:
    """Merge cast + entity records into name → public entity URL."""
    name_to_url: dict[str, str] = {}
    for group in (cast or [], entities or []):
        for ent in group:
            eid = ent.get("entity_id")
            name = str(ent.get("name") or "").strip()
            if eid is None or not name:
                continue
            name_to_url[name] = entity_url(
                public_base,
                campaign_id,
                int(eid),
                campaign_slug=campaign_slug,
            )
    return name_to_url


def linkify_recap(recap: str, name_to_url: dict[str, str]) -> str:
    """Replace known entity names with Discord markdown links (longest names first)."""
    if not recap or not name_to_url:
        return recap
    # Avoid replacing inside existing markdown links
    protected: list[str] = []

    def stash(match: re.Match) -> str:
        protected.append(match.group(0))
        return f"\x00LINK{len(protected) - 1}\x00"

    text = re.sub(r"\[[^\]]+\]\([^)]+\)", stash, recap)
    for name in sorted(name_to_url.keys(), key=len, reverse=True):
        url = name_to_url[name]
        if not name or not url:
            continue
        pattern = re.compile(rf"(?<!\w)({re.escape(name)})(?!\w)", re.IGNORECASE)

        def repl(match: re.Match, _url: str = url, _canon: str = name) -> str:
            return f"[{match.group(1)}]({_url})"

        text = pattern.sub(repl, text)
    for i, original in enumerate(protected):
        text = text.replace(f"\x00LINK{i}\x00", original)
    return text


def build_discord_message(
    *,
    title: str,
    recap: str,
    public_base: str,
    campaign_id: int,
    journal_entity_id: int | None,
    note_entity_id: int | None,
    entities: list[dict],
    campaign_slug: str = "",
) -> str:
    """entities: [{name, entity_id}, ...] created/updated this job (and optionally cast)."""
    name_to_url = build_name_to_url(
        public_base=public_base,
        campaign_id=campaign_id,
        entities=entities,
        campaign_slug=campaign_slug,
    )
    body = linkify_recap(recap.strip(), name_to_url)
    parts = [f"**{title}**", "", body, "", "**Kanka**"]
    if journal_entity_id:
        parts.append(
            "• [Session journal]("
            + entity_url(
                public_base,
                campaign_id,
                journal_entity_id,
                campaign_slug=campaign_slug,
            )
            + ")"
        )
    if note_entity_id:
        parts.append(
            "• [Transcript note]("
            + entity_url(
                public_base,
                campaign_id,
                note_entity_id,
                campaign_slug=campaign_slug,
            )
            + ")"
        )
    if entities:
        linked = []
        seen: set[int] = set()
        for ent in entities:
            eid = ent.get("entity_id")
            name = str(ent.get("name") or "").strip()
            if eid is None or not name or int(eid) in seen:
                continue
            seen.add(int(eid))
            linked.append(
                f"[{name}]("
                + entity_url(
                    public_base,
                    campaign_id,
                    int(eid),
                    campaign_slug=campaign_slug,
                )
                + ")"
            )
        if linked:
            parts.append("• Entities: " + ", ".join(linked))

    content = "\n".join(parts)
    if len(content) <= 1900:
        return content
    # Prefer keeping Kanka links: truncate recap middle
    footer_start = content.rfind("\n**Kanka**")
    if footer_start > 0:
        footer = content[footer_start:]
        head = content[:footer_start]
        budget = 1900 - len(footer) - 20
        if budget > 200:
            return head[:budget].rstrip() + "\n…(truncated)\n" + footer.lstrip()
    return content[:1900] + "\n…(truncated)"


def post_webhook(
    webhook_url: str,
    content: str,
    *,
    username: str = "",
    timeout: float = 30.0,
) -> None:
    payload: dict = {"content": content}
    if username.strip():
        payload["username"] = username.strip()[:80]
    r = httpx.post(webhook_url, json=payload, timeout=timeout)
    r.raise_for_status()
