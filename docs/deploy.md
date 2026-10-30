# Deploying LogicScout

Verified 2026-10-30 against official docs.

| Host | Card-free? | Notes |
|---|---|---|
| Hugging Face Spaces (Docker, CPU Basic: 2 vCPU/16 GB, free) | Pricing page does not demand a card | Primary. Port 7860, no sleep-spin issue documented for active use, ephemeral disk. https://huggingface.co/docs/hub/spaces-sdks-docker |
| Render free web service | Not stated on docs page (check signup) | Backup. 750 h/month, sleeps after 15 min idle, ephemeral disk. https://render.com/docs/free |
| Railway trial | Limited trial without card; $5 / 30 days | Short-lived; Limited Trial restricts outbound network (blocks model APIs) unless GitHub verified. https://docs.railway.com/reference/pricing/free-trial |
| Koyeb / Fly.io | Card required in practice | Not recommended |

## Hugging Face Space
Put `HF_TOKEN` (write access), `NEBIUS_API_KEY`, `TAVILY_API_KEY`, `LS_MODEL_DEEP`, `LS_MODEL_FAST` in the repo `.env`, then:

```
uv run --with huggingface_hub --with python-dotenv python deploy/hf/push.py
```

It creates the public Space `shafir-01/logicscout` (Docker, free cpu-basic), sets the secrets and variables (PORT=7860, LS_MAX_LIVE_RUNS=3), uploads the repo with `deploy/hf/README.md` as the Space README, and waits until it is RUNNING at https://shafir-01-logicscout.hf.space. The image builds `web/` with `npm ci && npm run build`; the API serves `web/dist`. The container runs as uid 1000 with a writable `/app/data`. `LS_SANDBOX_TOKEN` is generated per boot if unset. Disk is ephemeral.

## Render
New > Blueprint from the GitHub repo (render.yaml), fill secrets.

## Railway
`railway login` (browser), `railway init`, `railway up`, set variables in dashboard.

## Nebius
See deploy/nebius/README.md.
