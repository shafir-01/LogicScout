# Nebius AI Cloud deployment (Serverless AI)

Docs: https://docs.nebius.com/serverless , https://docs.nebius.com/cli/reference/ai/endpoint/create , https://docs.nebius.com/cli/reference/ai/job/create

Serverless AI runs containers as Endpoints (long-running, managed HTTPS URL) or Jobs (run to completion). Billing is per-second and usage-based, so a Nebius project with credits or billing is required (hackathon credits work). Nothing here is free by itself; do not run it without credits.

## CLI
Docs install only Ubuntu/macOS (use WSL or Cloud Shell on Windows):

    curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash && exec -l $SHELL
    nebius version
    nebius profile create --profile logicscout --endpoint api.nebius.cloud \
      --federation-endpoint auth.nebius.com --parent-id <PROJECT_ID>   # opens browser to log in

## 0. Push the image (public registry avoids credentials)
    docker build -t ghcr.io/shafir-01/logicscout:latest . && docker push ghcr.io/shafir-01/logicscout:latest

## (a) Endpoint
    nebius ai endpoint create --name logicscout \
      --image ghcr.io/shafir-01/logicscout:latest \
      --container-port 8787/http \
      --platform cpu-d3 --preset 4vcpu-16gb \
      --env LS_MODEL_DEEP=$LS_MODEL_DEEP --env LS_MODEL_FAST=$LS_MODEL_FAST \
      --env NEBIUS_API_KEY=$NEBIUS_API_KEY --env TAVILY_API_KEY=$TAVILY_API_KEY \
      --auth none --dry-run          # drop --dry-run to create
    nebius ai endpoint get <ENDPOINT_ID>     # see status.public_endpoints
    nebius ai endpoint logs <ENDPOINT_ID>

Platform/preset names vary by region: check `nebius ai endpoint create --help` and the console. Prefer `--env-secret KEY=SECRET_SELECTOR` (MysteryBox) for keys. Private image: add `--registry-username/--registry-password`.

## (b) Bench as a Job
    nebius ai job create --name logicscout-bench \
      --image ghcr.io/shafir-01/logicscout:latest \
      --container-command python --args "-m logicscout.bench --world relay --seeds 3" \
      --platform cpu-d3 --preset 4vcpu-16gb --timeout 2h \
      --env NEBIUS_API_KEY=$NEBIUS_API_KEY --env LS_MODEL_DEEP=$LS_MODEL_DEEP --env LS_MODEL_FAST=$LS_MODEL_FAST \
      --dry-run
    nebius ai job logs <JOB_ID>; nebius ai job delete <JOB_ID>
