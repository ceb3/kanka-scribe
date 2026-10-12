from kanka_scribe.prompts import (
    DEFAULT_ENTITY_TYPE_PROMPTS,
    assemble_detail_system,
    build_detail_messages,
    normalize_entity_type_prompts,
    parse_entity_type_prompts,
    resolve_entity_type_prompts,
)


def test_assemble_detail_system_matches_defaults():
    system = assemble_detail_system()
    assert "### character" in system
    assert "Player Character" in system
    assert DEFAULT_ENTITY_TYPE_PROMPTS["quest"] in system


def test_override_replaces_single_type_block():
    custom = "- type: MUST be Custom Hero\n- title: optional"
    system = assemble_detail_system({"character": custom})
    assert custom in system
    assert "Player Character" not in system
    assert DEFAULT_ENTITY_TYPE_PROMPTS["location"] in system


def test_normalize_strips_defaults_and_keeps_overrides():
    raw = normalize_entity_type_prompts(
        {
            "character": DEFAULT_ENTITY_TYPE_PROMPTS["character"],
            "quest": "- type: Epic only",
        }
    )
    parsed = parse_entity_type_prompts(raw)
    assert "character" not in parsed
    assert parsed["quest"] == "- type: Epic only"


def test_resolve_fills_missing_keys():
    effective = resolve_entity_type_prompts('{"item": "- type: Relic"}')
    assert effective["item"] == "- type: Relic"
    assert effective["creature"] == DEFAULT_ENTITY_TYPE_PROMPTS["creature"]


def test_build_detail_messages_uses_overrides():
    messages = build_detail_messages(
        "chunk",
        known_entities=[{"name": "Lyra", "type": "character"}],
        entity_type_prompts={"event": "- type: Festival only"},
    )
    system = messages[0]["content"]
    assert "Festival only" in system
    assert "Known entities" in system
    assert "character: Lyra" in system
