# Installation guide

## Requirements

- Docker and Docker Compose
- A Kanka campaign (CE or SaaS) and a **Personal Access Token** (Profile → API)
- An OpenAI-compatible chat completions endpoint (Ollama, vLLM, OpenAI, etc.)

## Local Docker (recommended)

From the repository root:

```bash
cp .env.example .env
# Set SECRET_KEY, SECRETS_FERNET_KEY, and BOOTSTRAP_ADMIN_PASSWORD at minimum.
# Generate a Fernet key, e.g.:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up --build
```

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | App/JWT signing secret |
| `SECRETS_FERNET_KEY` | Encrypts workspace PATs and API keys at rest |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | First admin when the DB is empty |
| `APP_PORT` | Host port (default `8000` for root Compose) |
| `HANDOFF_HOST_DIR` | Host directory mounted as `/handoff` for filesystem ingest |
| `DEFAULT_KANKA_PUBLIC_URL` | Default public UI base for Discord / entity links |
| `DEFAULT_LLM_BASE_URL_PLACEHOLDER` | Placeholder shown in Settings for the LLM URL |
| `KANKA_MAX_REQUESTS_PER_MINUTE` | Client-side Kanka pacing (default `24`) |
| `OIDC_*` | Optional OIDC login (leave issuer empty to disable) |

UI: http://localhost:8000 (or your `APP_PORT`).

## Production-style Compose

See [deploy/README.md](../deploy/README.md). Same app image, configurable publish
port (`APP_PORT`, default `8095`), Postgres data dir, and handoff mount.

```bash
cd deploy
cp .env.example .env
# edit secrets and paths
mkdir -p data/postgres data/handoff
docker compose -f compose.yaml up -d --build
```

## First-run setup

1. Sign in with the bootstrap admin credentials.
2. Open **Settings** and create a workspace.
3. Configure **Kanka**:
   - **CE:** `kanka_base_url` = your CE origin (e.g. `https://kanka.example`), API prefix `/1.0`, profile `ce`, paste PAT.
   - **SaaS:** base `https://api.kanka.io`, prefix `/1.0`, profile `saas`, paste SaaS PAT.
4. Click **Save & probe campaigns**, pick the campaign/world.
5. Set **Public site URL** if Discord links should use a different host than the API (CE reverse proxy). Override the app default with `DEFAULT_KANKA_PUBLIC_URL` in `.env` if you want a different blank-form default.
6. Configure **LLM**: OpenAI-compatible base URL (must include `/v1` if that is how your server exposes chat completions), model name, optional API key, and context length (used for automatic transcript chunking).
7. Ingest a transcript from **App** (paste or upload), or use the handoff API below.

## API sketch

```bash
# login
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"changeme"}'

# create workspace (set Kanka + LLM fields)
curl -s -X POST http://localhost:8000/api/v1/workspaces \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Home","kanka_base_url":"https://kanka.example","kanka_token":"...","kanka_campaign_id":1,"kanka_profile":"ce","llm_base_url":"http://llm:11434/v1","llm_model":"llama3.1","handoff_dir":"/handoff"}'

# ingest
curl -s -X POST http://localhost:8000/api/v1/ingest \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"workspace_id":1,"transcript":"..."}'
```

## Filesystem handoff (Craig-style)

Pipelines can drop paired files into the mounted handoff directory:

- `{archive}.transcript.txt`
- `{archive}.handoff.json` (schema version, title, session date, paths, status)

Mount that directory with `HANDOFF_HOST_DIR` and set the workspace `handoff_dir`
(typically `/handoff` inside the container), then:

```bash
curl -X POST http://localhost:8000/api/v1/ingest/handoff \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"workspace_id":1}'
```

Create an API key under **API keys** for unattended callers.

## OIDC

Set `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and `OIDC_REDIRECT_URI`
(must match your IdP’s allowed redirect). Start login at
`GET /api/v1/auth/oidc/login`.

## Kanka rate limits

Kanka CE defaults to about **30 API requests/minute**. Scribe defaults to
`KANKA_MAX_REQUESTS_PER_MINUTE=24` and retries on `429` using `Retry-After` /
backoff. Raise the env var only if you also raise CE’s `API_THROTTLE_LIMIT`.

## Development without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
export DATABASE_URL='sqlite+pysqlite:////tmp/kanka-scribe.db'
export SECRET_KEY=dev
export SECRETS_FERNET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
pytest
uvicorn kanka_scribe.main:app --reload
```
