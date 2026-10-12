from kanka_scribe.recap_entities import candidates_from_recap


RECAP = """
**Participants:** Lyra, Morpheus
**Locations:** Heatherland Village, Stonewatch, Camorra's Watch
**Quests / objectives:** Reinforce the barrier, Clear the beaver dam
**NPCs:** Lieutenant Donovan, Mayor of Stonewatch
**Items & discoveries:** barrier stone, beaver pelt
**Loose threads:** Morpheus death, weakened barrier

### Short summary
- Beat one

### Full report
The party met Donovan at the tavern.
"""


def test_candidates_from_recap_header_lists():
    found = candidates_from_recap(RECAP)
    by_type: dict[str, set[str]] = {}
    for c in found:
        by_type.setdefault(c.type, set()).add(c.name)
        assert c.confidence == "high"
    assert "Lyra" in by_type["character"]
    assert "Morpheus" in by_type["character"]
    assert "Heatherland Village" in by_type["location"]
    assert "Stonewatch" in by_type["location"]
    assert "Lieutenant Donovan" in by_type["character"]
    assert "barrier stone" in by_type["item"]
    assert "beaver pelt" in by_type["item"]
    assert "Reinforce the barrier" in by_type["quest"]
    assert "Clear the beaver dam" in by_type["quest"]


def test_quest_phrases_keep_and():
    text = (
        "**Quests / objectives:** Investigate and resolve the kobold problem, "
        "Escort the caravans"
    )
    found = candidates_from_recap(text)
    quests = {c.name for c in found if c.type == "quest"}
    assert "Investigate and resolve the kobold problem" in quests
    assert "Escort the caravans" in quests


def test_candidates_from_recap_strips_markdown_links():
    text = "**Locations:** [Heatherland](https://kanka.example/w/1/entities/9), Nowhere"
    found = candidates_from_recap(text)
    names = {c.name for c in found if c.type == "location"}
    assert names == {"Heatherland", "Nowhere"}
