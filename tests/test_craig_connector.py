import json
from pathlib import Path

from kanka_scribe.connectors.craig import CraigHandoffConnector


def test_list_and_fetch_pending(tmp_path: Path):
    transcript = tmp_path / "session.zip.transcript.txt"
    transcript.write_text("**alice:**\nhello\n")
    handoff = tmp_path / "session.zip.handoff.json"
    handoff.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "craig",
                "archive_id": "session.zip",
                "title": "Session - 2026-10-11 - Ruins",
                "recap_markdown": "recap",
                "transcript_path": transcript.name,
                "ingest_status": "pending",
            }
        )
    )
    conn = CraigHandoffConnector(tmp_path)
    pending = conn.list_pending()
    assert len(pending) == 1
    bundle = conn.fetch(pending[0])
    assert bundle.transcript.startswith("**alice:**")
    assert bundle.title.startswith("Session")
    conn.mark_ingested(pending[0], job_id=9)
    assert json.loads(handoff.read_text())["ingest_status"] == "ingested"
    assert conn.list_pending() == []
