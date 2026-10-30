"""NVIDIA Nemotron on Nebius Token Factory (OpenAI-compatible)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Literal

import openai

from logicscout import config
from logicscout.contracts import ModelCall

PROVIDER = "nebius-token-factory"
TIMEOUTS = {"deep": 120.0, "fast": 60.0}
MAX_TRANSIENT = 3
# Nemotron 3 reasons before answering; long reasoning hit the completion cap and leaked into `content`.
# Measured on Token Factory: thinking off answers the same JSON prompts in ~5s instead of 25s+/failure.
THINKING = os.getenv("LS_THINKING", "off").lower() in ("1", "on", "true")
MAX_TOKENS = int(os.getenv("LS_MAX_TOKENS", "6000"))
_THINK = re.compile(r"<think>.*?(</think>|$)", re.S | re.I)
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}
_SEMS: dict[int, asyncio.Semaphore] = {}


class LLMError(RuntimeError):
    pass


def _sem() -> asyncio.Semaphore:
    loop = id(asyncio.get_running_loop())
    if loop not in _SEMS:
        _SEMS[loop] = asyncio.Semaphore(int(os.getenv("LS_LLM_CONCURRENCY", "4")))
    return _SEMS[loop]


def strip_reasoning(text: str) -> str:
    text = _THINK.sub("", text or "")
    if "</think>" in text:  # reasoning emitted without the opening tag
        text = text.split("</think>", 1)[1]
    return text.strip()


def extract_json(text: str, schema: dict | None = None) -> dict:
    """First JSON object in the text; with a schema, prefer the first object that satisfies it."""
    found = list(_objects(strip_reasoning(text)))
    if not found:
        raise ValueError("no JSON object found in model output")
    if schema:
        for obj in found:
            if not check_schema(obj, schema):
                return obj
    return found[0]


def _objects(text: str):
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            yield obj
                            start = i
                    except json.JSONDecodeError:
                        pass
                    break
        start = text.find("{", start + 1)


def check_schema(obj: dict, schema: dict | None) -> list[str]:
    if not schema:
        return []
    errs = [f"missing key '{k}'" for k in schema.get("required", []) if k not in obj]
    for k, spec in (schema.get("properties") or {}).items():
        t = spec.get("type") if isinstance(spec, dict) else None
        if k in obj and isinstance(t, str) and t in _TYPES:
            v = obj[k]
            if not isinstance(v, _TYPES[t]) or (t in ("integer", "number") and isinstance(v, bool)):
                errs.append(f"key '{k}' must be {t}")
    return errs


class Nemotron:
    def __init__(
        self,
        client: Any = None,
        on_call: Callable[[ModelCall], Any] | None = None,
        prompt_log: str | Path | None = None,
        model_deep: str | None = None,
        model_fast: str | None = None,
        backoff: float = 1.0,
    ):
        self.model_deep = config.MODEL_DEEP if model_deep is None else model_deep
        self.model_fast = config.MODEL_FAST if model_fast is None else model_fast
        if client is None:
            if not config.NEBIUS_API_KEY:
                raise LLMError("NEBIUS_API_KEY is not set; add it to .env to use Nemotron on Nebius Token Factory")
            client = openai.AsyncOpenAI(base_url=config.NEBIUS_BASE_URL, api_key=config.NEBIUS_API_KEY, max_retries=0)
        self.client = client
        self.on_call = on_call
        self.prompt_log = Path(prompt_log) if prompt_log else None
        self.backoff = backoff
        self.calls: list[ModelCall] = []
        self.tokens = 0
        self.latencies: list[float] = []

    def model_for(self, tier: str) -> str:
        primary, other = (self.model_deep, self.model_fast) if tier == "deep" else (self.model_fast, self.model_deep)
        m = primary or other
        if not m:
            raise LLMError("no Nemotron model configured: set LS_MODEL_DEEP and/or LS_MODEL_FAST in .env "
                           "(run `uv run python -m logicscout.llm.models` to list ids)")
        return m

    def stats(self) -> dict:
        lat = sorted(self.latencies)
        return {
            "calls": len(self.calls),
            "ok": sum(c.ok for c in self.calls),
            "tokens": self.tokens,
            "latency_ms_avg": sum(lat) / len(lat) if lat else 0.0,
            "latency_ms_p50": lat[len(lat) // 2] if lat else 0.0,
            "escalations": sum(c.escalated for c in self.calls),
        }

    def _emit(self, call: ModelCall) -> None:
        self.calls.append(call)
        self.latencies.append(call.latency_ms)
        self.tokens += (call.prompt_tokens or 0) + (call.completion_tokens or 0)
        if self.on_call:
            self.on_call(call)

    def _log(self, purpose: str, model: str, system: str, user: str, text: str) -> None:
        if not self.prompt_log:
            return
        self.prompt_log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.time(), "purpose": purpose, "model": model, "system": system,
               "user": user, "response_text": text}
        with self.prompt_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def _fail(self, purpose, tier, model, t0, escalated, error, sha) -> None:
        self._emit(ModelCall(purpose=purpose, tier=tier, model=model, provider=PROVIDER,
                             latency_ms=(time.perf_counter() - t0) * 1000, ok=False,
                             escalated=escalated, error=error, request_sha=sha))

    async def _complete(self, purpose, tier, model, system, user, escalated):
        """Returns (text, ModelCall) for one successful completion, retrying transient errors."""
        sha = hashlib.sha256(json.dumps([model, system, user]).encode()).hexdigest()
        last = ""
        budget = MAX_TOKENS
        for attempt in range(MAX_TRANSIENT):
            t0 = time.perf_counter()
            try:
                async with _sem():
                    resp = await asyncio.wait_for(
                        self.client.chat.completions.create(
                            model=model,
                            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                            response_format={"type": "json_object"},
                            temperature=0.2,
                            max_tokens=budget,
                            extra_body={"chat_template_kwargs": {"enable_thinking": THINKING}},
                        ),
                        timeout=TIMEOUTS[tier],
                    )
            except (asyncio.TimeoutError, openai.APITimeoutError, openai.APIConnectionError,
                    openai.RateLimitError, openai.InternalServerError) as e:
                last = f"{type(e).__name__}: {e}"
                self._fail(purpose, tier, model, t0, escalated, last, sha)
                if attempt < MAX_TRANSIENT - 1:
                    await asyncio.sleep(self.backoff * 2**attempt)
                continue
            except openai.APIError as e:
                self._fail(purpose, tier, model, t0, escalated, str(e), sha)
                raise LLMError(f"{purpose}: provider error: {e}") from e
            usage = getattr(resp, "usage", None)
            msg = resp.choices[0].message
            text = msg.content or ""
            got = getattr(resp, "model", None) or model
            if getattr(resp.choices[0], "finish_reason", None) == "length" and attempt < MAX_TRANSIENT - 1:
                last = f"completion cut at max_tokens={budget}"
                self._fail(purpose, tier, model, t0, escalated, last, sha)
                budget *= 2  # reasoning and answer share the cap: retry with room
                continue
            call = ModelCall(purpose=purpose, tier=tier, model=got, provider=PROVIDER,
                             latency_ms=(time.perf_counter() - t0) * 1000,
                             prompt_tokens=getattr(usage, "prompt_tokens", None),
                             completion_tokens=getattr(usage, "completion_tokens", None),
                             ok=True, escalated=escalated, request_sha=sha)
            return text, call, got
        raise LLMError(f"{purpose}: model unavailable after {MAX_TRANSIENT} attempts ({last})")

    async def json(self, purpose: str, system: str, user: str, schema: dict | None = None,
                   tier: Literal["fast", "deep"] = "fast") -> dict:
        sys_full = system + "\n\nRespond with a single JSON object only, no prose or markdown."
        if schema:
            sys_full += "\nJSON schema to follow:\n" + json.dumps(schema)
        plan = [(tier, False, False), (tier, False, True)]
        if tier == "fast" and self.model_for("deep") != self.model_for("fast"):
            plan.append(("deep", True, False))
        err = ""
        for t, esc, repair in plan:
            msg = f"{user}\n\nYour previous answer was invalid: {err}. Return corrected JSON only." if repair else user
            text, call, got = await self._complete(purpose, t, self.model_for(t), sys_full, msg, esc)
            self._log(purpose, got, sys_full, msg, text)
            try:
                obj = extract_json(text, schema)
                errs = check_schema(obj, schema)
                err = "; ".join(errs)
            except ValueError as e:
                obj, err = None, str(e)
            if err:
                call.ok, call.error = False, f"invalid output: {err}"
            self._emit(call)
            if not err:
                return obj
        raise LLMError(f"{purpose}: model returned invalid JSON after retry/escalation: {err}")
