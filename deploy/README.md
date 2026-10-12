# Deploy kanka-scribe on docker host (`192.168.1.17`)

```bash
# from Code/kanka-scribe on a machine with ssh Host docker
ssh docker 'mkdir -p /opt/kanka-scribe /opt/stacks/kanka-scribe /mnt/backups/craig/handoff'
rsync -av --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'data' --exclude '*.egg-info' \
  ./ docker:/opt/kanka-scribe/
rsync -av deploy/compose.yaml deploy/.env.example docker:/opt/stacks/kanka-scribe/
# generate .env on host if missing, then:
ssh docker 'cd /opt/stacks/kanka-scribe && docker compose -f compose.yaml up -d --build'
```

LAN UI: http://192.168.1.17:8095

Kanka CE throttles API calls at **30/min** by default. Scribe paces itself via
`KANKA_MAX_REQUESTS_PER_MINUTE` (default **24**) and retries on `429` using
`Retry-After` / exponential backoff. Raise the env var only if you also raise
CE’s `API_THROTTLE_LIMIT`.
