# Production-style Compose

Use this stack when you want a named container deploy with a configurable publish
port and host handoff mount. For day-to-day local use, prefer the root
`docker-compose.yml` (see [docs/INSTALL.md](../docs/INSTALL.md)).

```bash
cd deploy
cp .env.example .env
# edit secrets, APP_PORT, HANDOFF_HOST_DIR, DEFAULT_KANKA_PUBLIC_URL, …
mkdir -p data/postgres data/handoff
docker compose -f compose.yaml up -d --build
```

| Variable | Purpose |
| --- | --- |
| `APP_PORT` | Host port mapped to the app (default `8095`) |
| `APP_BUILD_CONTEXT` | Path to the repo root for `docker build` (default `..`) |
| `POSTGRES_DATA_DIR` | Postgres data directory on the host |
| `HANDOFF_HOST_DIR` | Host directory mounted at `/handoff` |
| `DEFAULT_KANKA_PUBLIC_URL` | Default public Kanka UI base for Discord / links |
| `DEFAULT_LLM_BASE_URL_PLACEHOLDER` | Settings UI placeholder for the LLM base URL |
| `KANKA_MAX_REQUESTS_PER_MINUTE` | Client-side API pacing (stay under CE’s limit) |

Kanka CE throttles API calls at **30/min** by default. Scribe paces itself via
`KANKA_MAX_REQUESTS_PER_MINUTE` (default **24**) and retries on `429`.
