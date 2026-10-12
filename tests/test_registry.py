from kanka_scribe.registry import (
    alias_asset_type_id,
    allowed_modules,
    load_profile,
    module_path,
    visibility_id,
)


def test_ce_profile_has_modules_and_alias_type():
    profile = load_profile("ce")
    assert "character" in profile["modules"]
    assert module_path("ce", "character") == "characters"
    assert alias_asset_type_id("ce") == 3
    assert visibility_id("ce", "all") == 1
    assert "character" in allowed_modules("ce")


def test_saas_profile_loads():
    assert module_path("saas", "location") == "locations"
