# kanka-scribe

Ingest TTRPG session transcripts into **Kanka CE or kanka.io** using an external
OpenAI-compatible LLM. App login is separate from your Kanka PAT.

## Features (v1)

- FastAPI app + Postgres (Docker Compose)
- Email/password auth + optional OIDC hook
- Workspaces with encrypted Kanka PAT + LLM settings
- Ingest via JSON, file upload, or Craig handoff directory
- Journal + private transcript note; entity extract/sync
- Automatic transcript chunking from `llm_context_length`
- Vendored Kanka API docs + CE/SaaS overrides under `vendor/kanka-api-docs/`

## Quick start (local)

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:8000 — sign in, then upload or paste a transcript on `/ui/app`.
Default admin from `BOOTSTRAP_ADMIN_*`.

## Homelab deploy (docker host)

Source: `/opt/kanka-scribe` · stack: `/opt/stacks/kanka-scribe` · LAN: **http://192.168.1.17:8095**

```bash
# from this repo (no rsync on the docker host — use tar)
ssh docker 'mkdir -p /opt/kanka-scribe /opt/stacks/kanka-scribe /mnt/backups/craig/handoff'
tar -czf - --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' \
  --exclude='data' --exclude='*.egg-info' --exclude='.env' . \
  | ssh docker 'tar -C /opt/kanka-scribe -xzf -'
tar -C deploy -czf - compose.yaml .env.example README.md \
  | ssh docker 'tar -C /opt/stacks/kanka-scribe -xzf -'
ssh docker 'cd /opt/stacks/kanka-scribe && docker compose -f compose.yaml up -d --build'
```

Bootstrap password (first deploy only): `ssh docker 'cat /opt/stacks/kanka-scribe/.admin-pass.once'`

```bash
# login
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@localhost","password":"changeme"}'

# create workspace (set Kanka + LLM fields)
curl -s -X POST http://localhost:8000/api/v1/workspaces \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Home","kanka_base_url":"https://kanka.example","kanka_token":"...","kanka_campaign_id":1,"kanka_profile":"ce","llm_base_url":"http://ollama:11434/v1","llm_model":"llama3.1","handoff_dir":"/handoff"}'

# ingest
curl -s -X POST http://localhost:8000/api/v1/ingest \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"workspace_id":1,"transcript":"..."}'
```

### Connect Kanka CE

Set `kanka_base_url` to your CE origin (e.g. `https://kanka.example`),
`kanka_api_prefix` usually `/1.0`, `kanka_profile=ce`, and a Personal Access Token
from Profile → API.

### Connect Kanka.io (SaaS)

Use `https://api.kanka.io`, prefix `/1.0`, `kanka_profile=saas`, and a SaaS PAT.

### Craig handoff

`session-pipeline` writes `{archive}.handoff.json` + `{archive}.transcript.txt`.
Mount that directory as `HANDOFF_HOST_DIR` and set the workspace `handoff_dir`
(e.g. `/handoff`), then:

```bash
curl -X POST http://localhost:8000/api/v1/ingest/handoff \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"workspace_id":1}'
```

### OIDC

Set `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`.
Start at `GET /api/v1/auth/oidc/login`.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
uvicorn kanka_scribe.main:app --reload
```

## License

MIT
