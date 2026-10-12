from kanka_scribe.discord_notify import (
    build_discord_message,
    entity_url,
    linkify_recap,
)


def test_entity_url_prefers_campaign_slug():
    assert (
        entity_url("https://kanka.example", 1, 10, campaign_slug="kelmorth")
        == "https://kanka.example/w/kelmorth/entities/10"
    )
    assert (
        entity_url("https://kanka.example", 1, 10)
        == "https://kanka.example/w/1/entities/10"
    )


def test_linkify_and_message_includes_kanka_links():
    recap = "Lyra opened the door. The party followed."
    linked = linkify_recap(
        recap,
        {"Lyra": "https://kanka.example/w/kelmorth/entities/10"},
    )
    assert "[Lyra](https://kanka.example/w/kelmorth/entities/10)" in linked

    msg = build_discord_message(
        title="Session - 2026-10-11 - Ruins",
        recap=recap,
        public_base="https://kanka.example",
        campaign_id=1,
        campaign_slug="kelmorth",
        journal_entity_id=100,
        note_entity_id=101,
        entities=[
            {"name": "Lyra", "entity_id": 10},
            {"name": "Northern Gate", "entity_id": 11},
        ],
    )
    assert "**Session - 2026-10-11 - Ruins**" in msg
    assert "[Session journal](https://kanka.example/w/kelmorth/entities/100)" in msg
    assert "[Transcript note](https://kanka.example/w/kelmorth/entities/101)" in msg
    assert "[Lyra](https://kanka.example/w/kelmorth/entities/10)" in msg
    assert "[Northern Gate](https://kanka.example/w/kelmorth/entities/11)" in msg
