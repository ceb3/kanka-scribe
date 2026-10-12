from kanka_scribe.discord_notify import build_name_to_url, linkify_recap
from kanka_scribe.prompts import MERGE_SYSTEM, SYSTEM
from kanka_scribe.session_notes import (
    SessionMeta,
    build_transcript_note,
    parse_session_meta,
)


def test_prompts_ask_for_field_report_structure():
    for text in (SYSTEM, MERGE_SYSTEM):
        assert "Short summary" in text
        assert "Full report" in text
        assert "Participants" in text
        assert "Opening" not in text or "do not use" in text.lower()


def test_parse_session_meta_fills_unknowns():
    meta = parse_session_meta('{"session":"4","date":"2026-10-11","participants":["Lyra"]}')
    assert meta.session == "4"
    assert meta.date == "2026-10-11"
    assert meta.time == "Unknown"
    assert meta.participants == ["Lyra"]
    assert meta.locations == []


def test_parse_session_meta_invalid_json_returns_unknowns():
    meta = parse_session_meta("not json")
    assert meta.session == "Unknown"
    assert meta.date == "Unknown"
    assert meta.time == "Unknown"


def test_transcript_note_header_then_body():
    note = build_transcript_note(
        transcript="Player: we go north",
        meta=SessionMeta(
            session="3",
            date="2026-10-11",
            time="Unknown",
            start="Unknown",
            end="Unknown",
            duration="Unknown",
            participants=["Lyra", "Morpheus"],
            locations=["Heatherland"],
        ),
        source="upload",
        name_to_url={
            "Lyra": "https://kanka.example/w/1/entities/10",
            "Heatherland": "https://kanka.example/w/1/entities/20",
        },
    )
    assert "**Session:** 3" in note
    assert "**Date:** 2026-10-11" in note
    assert "**Time:** Unknown" in note
    assert "**Duration:** Unknown" in note
    assert "[Lyra](https://kanka.example/w/1/entities/10)" in note
    assert "Morpheus" in note
    assert "[Heatherland](https://kanka.example/w/1/entities/20)" in note
    assert "**Source:** upload" in note
    assert note.index("---") < note.index("Player: we go north")
    assert note.rstrip().endswith("Player: we go north")


def test_enrich_meta_from_title_sets_date():
    from kanka_scribe.session_notes import enrich_meta_from_title

    meta = SessionMeta()
    enrich_meta_from_title(meta, "Session - 2026-10-11")
    assert meta.date == "2026-10-11"


def test_normalize_and_parse_played_dates():
    from kanka_scribe.session_notes import (
        enrich_meta_from_recap,
        normalize_iso_date,
        parse_date_from_text,
    )

    assert normalize_iso_date("December 14, 2025") == "2025-12-14"
    assert normalize_iso_date("14 December 2025") == "2025-12-14"
    assert normalize_iso_date("2025-12-14") == "2025-12-14"
    assert (
        parse_date_from_text(
            "Session Number: 1\nDate Played: December 14, 2025\nParty Level: 3"
        )
        == "2025-12-14"
    )
    meta = SessionMeta()
    enrich_meta_from_recap(
        meta,
        "**Date Played:** December 14, 2025\n**Session Number:** 1\n",
    )
    assert meta.date == "2025-12-14"
    assert meta.session == "1"


def test_build_name_to_url_merges_cast_and_entities():
    urls = build_name_to_url(
        public_base="https://kanka.example",
        campaign_id=1,
        cast=[{"name": "Lyra", "entity_id": 10}],
        entities=[{"name": "Heatherland", "entity_id": 20}],
    )
    assert urls["Lyra"] == "https://kanka.example/w/1/entities/10"
    assert urls["Heatherland"] == "https://kanka.example/w/1/entities/20"
    linked = linkify_recap("Lyra reached Heatherland.", urls)
    assert "[Lyra](" in linked and "[Heatherland](" in linked
