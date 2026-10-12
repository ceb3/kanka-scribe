from kanka_scribe.session_notes import SessionMeta, build_transcript_header
from kanka_scribe.transcript_clean import (
    apply_timing_to_meta,
    build_speaker_map,
    extract_timestamps,
    format_duration,
    remap_speakers,
)


CAST = [
    {
        "name": "Morpheus",
        "aliases": ["charlie", "Charlie B"],
        "entity_id": 1,
    },
    {
        "name": "Lyra",
        "aliases": ["alice"],
        "entity_id": 2,
    },
]


def test_build_speaker_map_includes_names_and_aliases():
    mapping = build_speaker_map(CAST)
    assert mapping["morpheus"] == "Morpheus"
    assert mapping["charlie"] == "Morpheus"
    assert mapping["charlie b"] == "Morpheus"
    assert mapping["alice"] == "Lyra"


def test_remap_craig_style_speaker_blocks():
    raw = "**charlie:**\nHello there.\n\n**alice:**\nWe go north."
    out = remap_speakers(raw, CAST)
    assert out.startswith("**Morpheus:**")
    assert "**Lyra:**" in out
    assert "**charlie:**" not in out
    assert "Hello there." in out


def test_remap_plain_speaker_prefix_lines():
    raw = "Charlie B: I open the door.\nUnknownGuest: hi"
    out = remap_speakers(raw, CAST)
    assert out.startswith("Morpheus: I open the door.")
    assert "UnknownGuest: hi" in out


def test_extract_timestamps_and_duration():
    text = "[00:01:00] start\n[01:30:00] later\n[1:35:00] end"
    stamps = extract_timestamps(text)
    assert stamps[0] == 60
    assert stamps[-1] == 1 * 3600 + 35 * 60
    assert format_duration(stamps[-1] - stamps[0]) == "1h 34m"


def test_apply_timing_to_meta_and_header():
    meta = SessionMeta(date="2026-10-11")
    text = "[00:00:10] hi\n[02:05:00] bye"
    apply_timing_to_meta(meta, text)
    assert meta.start == "00:00:10"
    assert meta.end == "02:05:00"
    assert meta.duration == "2h 4m 50s"
    header = build_transcript_header(meta, source="craig")
    assert "**Start:** 00:00:10" in header
    assert "**End:** 02:05:00" in header
    assert "**Duration:** 2h 4m 50s" in header


def test_no_timestamps_leaves_timing_unknown():
    meta = SessionMeta()
    apply_timing_to_meta(meta, "no stamps here")
    assert meta.start == "Unknown"
    assert meta.end == "Unknown"
    assert meta.duration == "Unknown"
