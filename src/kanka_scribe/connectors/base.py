from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Handoff:
    id: str
    source: str
    title: str = ""
    session_date: str = ""
    path: str = ""


@dataclass
class TranscriptBundle:
    transcript: str
    title: str = ""
    recap_markdown: str = ""
    archive_id: str = ""
    source: str = "manual"
    meta: dict | None = None


class Connector(Protocol):
    def list_pending(self) -> list[Handoff]: ...

    def fetch(self, handoff: Handoff) -> TranscriptBundle: ...
