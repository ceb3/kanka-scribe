from types import SimpleNamespace

from kanka_scribe.kanka_campaign import (
    apply_campaign_record,
    find_campaign,
    public_campaign_ref,
    public_campaign_url,
)


def test_public_ref_prefers_slug():
    assert public_campaign_ref(campaign_id=1, campaign_slug="kelmorth") == "kelmorth"
    assert public_campaign_ref(campaign_id=1, campaign_slug="") == "1"
    assert public_campaign_ref(campaign_id=1, campaign_slug="  ") == "1"


def test_public_campaign_url():
    assert (
        public_campaign_url(
            "https://kanka.example",
            campaign_id=1,
            campaign_slug="kelmorth",
        )
        == "https://kanka.example/w/kelmorth"
    )


def test_apply_campaign_record_sets_and_clears_slug():
    ws = SimpleNamespace(kanka_campaign_name="", kanka_campaign_slug="")
    assert apply_campaign_record(
        ws, {"id": 1, "name": "Kelmorth", "slug": "kelmorth"}
    )
    assert ws.kanka_campaign_name == "Kelmorth"
    assert ws.kanka_campaign_slug == "kelmorth"
    assert apply_campaign_record(ws, {"id": 1, "name": "Kelmorth", "slug": ""})
    assert ws.kanka_campaign_slug == ""


def test_find_campaign():
    campaigns = [{"id": 1, "slug": "kelmorth"}, {"id": 2, "slug": "other"}]
    assert find_campaign(campaigns, 1)["slug"] == "kelmorth"
    assert find_campaign(campaigns, 9) is None
