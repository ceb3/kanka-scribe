"""Campaign id vs public slug helpers for Kanka UI URLs."""

from __future__ import annotations


def campaign_slug_from_record(record: dict | None) -> str:
    if not isinstance(record, dict):
        return ""
    return str(record.get("slug") or "").strip()


def campaign_name_from_record(record: dict | None) -> str:
    if not isinstance(record, dict):
        return ""
    return str(record.get("name") or "").strip()


def public_campaign_ref(*, campaign_id: int | None, campaign_slug: str = "") -> str:
    """Path segment for /w/{ref}/… — prefer slug when Kanka has one."""
    slug = (campaign_slug or "").strip()
    if slug:
        return slug
    if campaign_id is None:
        return ""
    return str(campaign_id)


def public_campaign_url(
    public_base: str,
    *,
    campaign_id: int | None,
    campaign_slug: str = "",
) -> str:
    base = (public_base or "").rstrip("/")
    ref = public_campaign_ref(campaign_id=campaign_id, campaign_slug=campaign_slug)
    if not base or not ref:
        return base
    return f"{base}/w/{ref}"


def find_campaign(campaigns: list[dict], campaign_id: int | None) -> dict | None:
    if campaign_id is None:
        return None
    for item in campaigns:
        try:
            if int(item.get("id", 0)) == int(campaign_id):
                return item
        except (TypeError, ValueError):
            continue
    return None


def apply_campaign_record(workspace, record: dict | None) -> bool:
    """Update workspace name/slug from a campaigns API record. Returns True if changed."""
    if not record:
        return False
    name = campaign_name_from_record(record)
    slug = campaign_slug_from_record(record)
    changed = False
    if name and getattr(workspace, "kanka_campaign_name", "") != name:
        workspace.kanka_campaign_name = name
        changed = True
    # Always sync slug (including clearing when Kanka has none)
    current = getattr(workspace, "kanka_campaign_slug", "") or ""
    if current != slug:
        workspace.kanka_campaign_slug = slug
        changed = True
    return changed
