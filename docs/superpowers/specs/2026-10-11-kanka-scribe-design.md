# kanka-scribe design

## Goal

Releasable Docker app that ingests TTRPG transcripts, uses an external
OpenAI-compatible LLM for journal summaries and entity extraction, and writes
to **Kanka CE or paid kanka.io** via PAT. App auth is independent of Kanka
(password + optional OIDC). v1 transcript source: Craig → Whisper handoff from
`session-pipeline`. Later connectors: Notion, Google Docs, DungeonWhisperer.

## Decisions

| Topic | Choice |
| --- | --- |
| Product / repo | `kanka-scribe` at `Code/kanka-scribe` |
| Hosting | Docker Compose (app + Postgres) |
| App auth | Email/password (argon2) + optional OIDC; JWT bearer for APIs |
| Kanka auth | Per-workspace PAT + base URL + API prefix + campaign id |
| LLM | OpenAI-compatible `/v1/chat/completions` |
| API contract | Vendored `vendor/kanka-api-docs/1.0` + CE/SaaS overrides |
| Entry format | HTML for TipTap (markdown converted before write) |
| Craig | session-pipeline strips Kanka; writes handoff files |

## Handoff schema (v1)

Files beside Craig zip or under `HANDOFF_DIR`:

- `{archive}.transcript.txt`
- `{archive}.handoff.json`:

```json
{
  "schema_version": 1,
  "source": "craig",
  "archive_id": "example.flac.zip",
  "session_date": "2026-10-10",
  "title": "Session - 2026-10-10 - Story Title",
  "recap_markdown": "…",
  "transcript_path": "example.flac.zip.transcript.txt",
  "ingest_status": "pending"
}
```

## APIs

Authenticated with app JWT:

- `POST /api/v1/ingest` — JSON transcript
- `POST /api/v1/ingest/upload` — text file
- `POST /api/v1/ingest/handoff` — import from handoff dir
- `GET /api/v1/jobs/{id}`
- Workspace + auth routes under `/api/v1/`

## Job pipeline

1. Normalize transcript
2. LLM recap if missing → HTML
3. LLM title if missing
4. Create journal + private note
5. Chunk extract → merge → match/create → posts + alias assets
6. Store job result

## Out of scope v1

Notion/GDocs/DungeonWhisperer implementations; Plugin Library; billing.
