from kanka_scribe.entity_extract import EntityCandidate, _merge_fields, merge_candidates
from kanka_scribe.kanka_entities import (
    memberships_from_character_fields,
    normalize_module_type,
    _trait_arrays,
)
from kanka_scribe.prompts import DETAIL_SYSTEM


def test_detail_prompt_has_per_type_field_sections():
    for label in (
        "### character",
        "### location",
        "### organisation",
        "### quest",
        "### creature",
        "### item",
        "### event",
        "NPC",
        "Player Character",
        "Deity",
        "organisations",
        "instigator",
    ):
        assert label in DETAIL_SYSTEM


def test_normalize_character_type_vocabulary():
    assert normalize_module_type("character", "NPC") == "NPC"
    assert normalize_module_type("character", "Player Character") == "Player Character"
    assert normalize_module_type("character", "PC") == "Player Character"
    assert normalize_module_type("character", "Sentinel officer") == "NPC"
    assert normalize_module_type("organisation", "Cult") == "Cult"
    assert normalize_module_type("organisation", "street gang") == "Gang"
    assert normalize_module_type("quest", "Side Quest") == "Sidequest"
    assert normalize_module_type("quest", "Main") == "Main"
    assert normalize_module_type("quest", "personal arc") == "Character Arc"
    assert normalize_module_type("item", "sword") == "Weapon"
    assert normalize_module_type("item", "healing potion") == "Potion"
    assert normalize_module_type("item", "map") == "Artifact"
    assert normalize_module_type("creature", "Mythical beast") == "Mythical"
    assert normalize_module_type("location", "Kingdom") == "Kingdom"


def test_memberships_from_character_fields():
    cands = [
        EntityCandidate(
            type="character",
            name="Lieutenant Donovan",
            fields={
                "organisations": [
                    {"name": "the Sentinels", "role": "Lieutenant"},
                ]
            },
        )
    ]
    mems = memberships_from_character_fields(cands)
    assert mems == [
        {
            "character": "Lieutenant Donovan",
            "organisation": "the Sentinels",
            "role": "Lieutenant",
        }
    ]


def test_trait_arrays():
    names, entries = _trait_arrays(
        [
            {"name": "Hair", "entry": "Grey cloak"},
            {"name": "Demeanor", "entry": "Professional"},
            "ignored",
        ]
    )
    assert names == ["Hair", "Demeanor"]
    assert entries == ["Grey cloak", "Professional"]


def test_merge_fields_unions_lists_and_keeps_richer_strings():
    merged = _merge_fields(
        {"type": "NPC", "locations": ["A"], "age": "1"},
        {"type": "Sentinel officer", "locations": ["B", "A"], "age": ""},
    )
    assert merged["type"] == "Sentinel officer"
    assert set(merged["locations"]) == {"A", "B"}
    assert merged["age"] == "1"


def test_merge_candidates_keeps_fields():
    a = EntityCandidate(
        type="character",
        name="Donovan",
        summary="short",
        fields={"type": "NPC", "locations": ["Camorra's Watch"]},
    )
    b = EntityCandidate(
        type="character",
        name="Lieutenant Donovan",
        aliases=["Donovan"],
        summary="much longer summary about the officer briefing the party " * 3,
        fields={"sex": "Male", "locations": ["Heatherland"]},
    )
    merged = merge_candidates([a, b])
    assert len(merged) == 1
    assert merged[0].fields.get("sex") == "Male"
    assert "Camorra's Watch" in merged[0].fields.get("locations", [])
    assert "Heatherland" in merged[0].fields.get("locations", [])
