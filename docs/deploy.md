# Deploying LogicScout

Verified 2026-10-30 against official docs.

| Host | Card-free? | Notes |
|---|---|---|
| Hugging Face Spaces (Docker, CPU Basic: 2 vCPU/16 GB, free) | Pricing page does not demand a card | Primary. Port 7860, no sleep-spin issue documented for active use, ephemeral disk. https://huggingface.co/docs/hub/spaces-sdks-docker |
| Render free web service | Not stated on docs page (check signup) | Backup. 750 h/month, sleeps after 15 min idle, ephemeral disk. https://render.com/docs/free |
| Railway trial | Limited trial without card; $5 / 30 days | Short-lived; Limited Trial restricts outbound network (blocks model APIs) unless GitHub verified. https://docs.railway.com/reference/pricing/free-trial |
| Koyeb / Fly.io | Card required in practice | Not recommended |

## Hugging Face Space
Create a Docker Space, push the repo with `deploy/hf/README.md` as the root README.md, add secrets (NEBIUS_API_KEY, TAVILY_API_KEY, LS_MODEL_DEEP, LS_MODEL_FAST, LS_SANDBOX_TOKEN) and variable PORT=7860. Container runs as uid 1000 (the Dockerfile user matches).

## Render
New > Blueprint from the GitHub repo (render.yaml), fill secrets.

## Railway
`railway login` (browser), `railway init`, `railway up`, set variables in dashboard.

## Nebius
See deploy/nebius/README.md.
