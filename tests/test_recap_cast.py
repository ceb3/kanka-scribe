from kanka_scribe.kanka_client import sanitize_cast_aliases
from kanka_scribe.kanka_entities import (
    EntityRef,
    _resolve_ref_list,
    is_player_character_type,
)
from kanka_scribe.prompts import format_cast_block
from kanka_scribe.recap_entities import candidates_from_cast, candidates_from_recap


def test_is_player_character_type():
    assert is_player_character_type("Player Character")
    assert is_player_character_type("PC")
    assert not is_player_character_type("NPC")
    assert not is_player_character_type("")
    assert not is_player_character_type(None)


def test_sanitize_cast_aliases_drops_other_pc_primary_names():
    cast = [
        {
            "name": "Ava",
            "aliases": ["the oracle", "Borin"],  # Borin is another PC
            "character_type": "Player Character",
        },
        {
            "name": "Borin",
            "aliases": ["B"],
            "character_type": "Player Character",
        },
        {
            "name": "Nub",  # untyped leftover stub
            "aliases": [],
            "character_type": "",
        },
        {
            "name": "Hilarion",
            "aliases": ["Nub"],  # OK: stub is not a PC
            "character_type": "Player Character",
        },
    ]
    cleaned = sanitize_cast_aliases(cast)
    ava = next(c for c in cleaned if c["name"] == "Ava")
    assert ava["aliases"] == ["the oracle"]
    borin = next(c for c in cleaned if c["name"] == "Borin")
    assert borin["aliases"] == ["B"]
    hil = next(c for c in cleaned if c["name"] == "Hilarion")
    assert hil["aliases"] == ["Nub"]


def test_format_cast_block_lists_pcs_first():
    cast = [
        {"name": "Mayor Quill", "aliases": [], "character_type": "NPC"},
        {
            "name": "Ava",
            "aliases": ["the oracle"],
            "character_type": "Player Character",
        },
        {"name": "Borin", "aliases": [], "character_type": "Player Character"},
        {"name": "Untyped Guard", "aliases": [], "character_type": ""},
    ]
    block = format_cast_block(cast)
    assert block.index("Player Characters") < block.index("Other known characters")
    assert block.index("- Ava") < block.index("- Mayor Quill")
    assert "Untyped Guard" in block
    assert "do not merge into Player Characters" in block


def test_cast_candidates_only_player_characters():
    cast = [
        {
            "name": "Ava",
            "aliases": ["the oracle"],
            "character_type": "Player Character",
        },
        {"name": "Mayor Quill", "aliases": [], "character_type": "NPC"},
        {"name": "Untyped Guard", "aliases": [], "character_type": ""},
    ]
    found = candidates_from_cast(cast)
    assert {c.name for c in found} == {"Ava"}
    ava = found[0]
    assert "the oracle" in ava.aliases
    assert ava.type == "character"
    assert ava.confidence == "high"
    assert ava.fields.get("type") == "Player Character"


def test_resolve_ref_list_prefers_unique_pc():
    npc = EntityRef("character", 1, 10, "Shared Name", False, "NPC")
    pc = EntityRef("character", 2, 20, "Shared Name", False, "Player Character")
    match, ambiguous = _resolve_ref_list([npc, pc])
    assert not ambiguous
    assert match is not None
    assert match.entity_id == 20


def test_recap_organisations_and_events():
    recap = """
**Organisations:** Roving Guard, Church of the Barrier
**Events:** Battle at the Dam, Death of Morpheus
"""
    found = candidates_from_recap(recap)
    orgs = {c.name for c in found if c.type == "organisation"}
    events = {c.name for c in found if c.type == "event"}
    assert "Roving Guard" in orgs
    assert "Church of the Barrier" in orgs
    assert "Battle at the Dam" in events
    assert "Death of Morpheus" in events
