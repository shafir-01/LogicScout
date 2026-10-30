"""Tests run exactly as in CI: no provider keys, whatever the local .env holds."""
import os

for _key in ("NEBIUS_API_KEY", "TAVILY_API_KEY", "LS_MODEL_DEEP", "LS_MODEL_FAST", "HF_TOKEN"):
    os.environ[_key] = ""  # set before logicscout.config runs load_dotenv, which never overrides
