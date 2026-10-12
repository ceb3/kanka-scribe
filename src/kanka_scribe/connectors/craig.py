from __future__ import annotations

import json
from pathlib import Path

from kanka_scribe.connectors.base import Handoff, TranscriptBundle


class CraigHandoffConnector:
    """Filesystem handoff from session-pipeline (Craig → Whisper → Discord)."""

    def __init__(self, handoff_dir: str | Path) -> None:
        self.root = Path(handoff_dir)

    def list_pending(self) -> list[Handoff]:
        if not self.root.is_dir():
            return []
        pending: list[Handoff] = []
        for path in sorted(self.root.glob("*.handoff.json")):
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("ingest_status", "pending") != "pending":
                continue
            pending.append(
                Handoff(
                    id=str(data.get("archive_id") or path.stem),
                    source=str(data.get("source") or "craig"),
                    title=str(data.get("title") or ""),
                    session_date=str(data.get("session_date") or ""),
                    path=str(path),
                )
            )
        return pending

    def fetch(self, handoff: Handoff) -> TranscriptBundle:
        path = Path(handoff.path)
        data = json.loads(path.read_text())
        transcript_name = data.get("transcript_path") or ""
        transcript_path = path.parent / transcript_name
        if not transcript_path.is_file():
            # fallback: sibling of handoff
            archive = data.get("archive_id", "")
            alt = path.parent / f"{archive}.transcript.txt"
            if alt.is_file():
                transcript_path = alt
            else:
                raise FileNotFoundError(f"transcript missing for {path}")
        return TranscriptBundle(
            transcript=transcript_path.read_text(),
            title=str(data.get("title") or ""),
            recap_markdown=str(data.get("recap_markdown") or ""),
            archive_id=str(data.get("archive_id") or handoff.id),
            source="craig",
            meta=data,
        )

    def mark_ingested(self, handoff: Handoff, job_id: int | None = None) -> None:
        path = Path(handoff.path)
        data = json.loads(path.read_text())
        data["ingest_status"] = "ingested"
        if job_id is not None:
            data["kanka_scribe_job_id"] = job_id
        path.write_text(json.dumps(data, indent=2) + "\n")


class NotionConnectorStub:
    """Stub — Notion connector out of scope for v1."""

    def list_pending(self) -> list[Handoff]:
        return []

    def fetch(self, handoff: Handoff) -> TranscriptBundle:
        raise NotImplementedError("Notion connector not implemented in v1")
