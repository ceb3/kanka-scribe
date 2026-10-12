# kanka-scribe

Ingest TTRPG session transcripts into **Kanka** (self-hosted Community Edition or
[kanka.io](https://kanka.io)) using any OpenAI-compatible LLM. App login is
separate from your Kanka personal access token.

## Features

- **Session journals** — LLM “Goblin Scribe” recaps with a Session Overview structure (cast, beats, open threads)
- **Entity pipeline** — extract characters, locations, organisations, creatures, quests, items, and events; match existing Kanka entities (aliases + Types); write detail posts
- **Editable prompts** — per-workspace recap system prompt and per-entity-type detail prompts
- **Kanka CE & SaaS** — configurable API base URL, prefix, and profile; HTML TipTap-friendly entries; campaign slug-aware public links
- **Ingest options** — paste JSON/text, upload a transcript file, or pick up Craig-style filesystem handoffs
- **Workspaces** — encrypted Kanka PAT + LLM credentials; multi-user membership
- **Auth** — email/password bootstrap admin; optional OIDC; API keys for automation
- **Discord notifications** — optional webhook with journal / entity links
- **Rate-limit aware** — client pacing and `429` retries for Kanka CE throttles
- **Docker-first** — Compose app + Postgres; vendored Kanka API docs under `vendor/kanka-api-docs/`

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:8000 — sign in with `BOOTSTRAP_ADMIN_*` from `.env`, create a
workspace (Kanka PAT + LLM), then ingest a transcript on `/ui/app`.

Full setup (production Compose, Kanka/LLM wiring, handoff, OIDC): **[docs/INSTALL.md](docs/INSTALL.md)**.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
uvicorn kanka_scribe.main:app --reload
```

## License

MIT
