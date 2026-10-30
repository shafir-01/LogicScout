# Models

LogicScout reasons with NVIDIA Nemotron served by Nebius Token Factory (OpenAI-compatible API).

- Base URL: `https://api.tokenfactory.nebius.com/v1/` (env `NEBIUS_BASE_URL`; a regional host
  `https://api.tokenfactory.us-central1.nebius.com/v1/` also appears in Nebius material).
- Auth: `Authorization: Bearer $NEBIUS_API_KEY`.
- Nemotron family listed by Nebius: Nemotron 3 Nano (30B), Nemotron 3 Nano Omni, Nemotron 3 Super (120B), Nemotron 3 Ultra (550B).
  Confirmed ID from Nebius: `nvidia/nemotron-3-super-120b-a12b`. Other IDs must be taken from
  `uv run python -m logicscout.llm.models` (GET /models); do not guess.
- Config: `LS_MODEL_DEEP` = strongest Nemotron available (Ultra if present), `LS_MODEL_FAST` = smaller Nemotron.
- Client requests `response_format={"type":"json_object"}`, strips `<think>` blocks (and ignores
  `reasoning_content`), extracts the first balanced JSON object and validates required keys/types.

Verify: `uv run python -m logicscout.llm.smoke`.

Sources:
- https://nebius.com/blog/posts/nemotron3-super-now-available
- https://nebius.com/services/token-factory/nemotron
