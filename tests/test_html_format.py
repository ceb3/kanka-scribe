from kanka_scribe.html_format import (
    html_entry,
    markdown_fragment_to_html,
    markdown_to_kanka_html,
    rewrite_campaign_links,
)


def test_markdown_links_become_anchors():
    html = markdown_to_kanka_html(
        "[Morpheus](https://kanka.example/w/kelmorth/entities/13)"
    )
    assert '<a href="https://kanka.example/w/kelmorth/entities/13">Morpheus</a>' in html


def test_rewrite_campaign_id_path_to_slug():
    raw = "see https://kanka.example/w/1/entities/17 and /w/1/entities/13"
    assert (
        rewrite_campaign_links(raw, campaign_id=1, campaign_slug="kelmorth")
        == "see https://kanka.example/w/kelmorth/entities/17 and /w/kelmorth/entities/13"
    )


def test_html_entry_converts_markdown_in_evidence():
    entry = html_entry(
        "Mentioned in session recap (Participants).",
        [
            "**Participants:** [Morpheus](https://kanka.example/w/1/entities/13)",
        ],
        campaign_id=1,
        campaign_slug="kelmorth",
    )
    assert "<strong>Participants:</strong>" in entry
    assert '<a href="https://kanka.example/w/kelmorth/entities/13">Morpheus</a>' in entry
    assert "](" not in entry
    assert "/w/1/" not in entry


def test_fragment_unwraps_paragraph():
    assert (
        markdown_fragment_to_html("**Nub**")
        == "<strong>Nub</strong>"
    )
