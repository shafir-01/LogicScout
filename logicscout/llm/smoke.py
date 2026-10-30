"""One fast + one deep live call: uv run python -m logicscout.llm.smoke"""
from __future__ import annotations

import asyncio
import json

from logicscout.llm.nemotron import Nemotron

SCHEMA = {"type": "object", "required": ["ok", "reason"],
          "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}}}


async def main() -> None:
    llm = Nemotron(on_call=lambda c: print(c.model_dump_json()))
    for tier in ("fast", "deep"):
        out = await llm.json("smoke", "You are a health check.",
                             'Return {"ok": true, "reason": "<one short sentence>"}.', SCHEMA, tier)
        print(tier, json.dumps(out))
    print(json.dumps(llm.stats()))


if __name__ == "__main__":
    asyncio.run(main())
