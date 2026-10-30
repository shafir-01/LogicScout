import asyncio
from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from logicscout.llm.nemotron import LLMError, Nemotron, extract_json, strip_reasoning


class FakeCompletions:
    def __init__(self, script):
        self.script = list(script)

    async def create(self, model, **kw):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return NS(model=f"prov/{model}", usage=NS(prompt_tokens=3, completion_tokens=2),
                  choices=[NS(message=NS(content=item))])


class FakeClient:
    def __init__(self, script):
        self.chat = NS(completions=FakeCompletions(script))


def mk(script, **kw):
    calls = []
    llm = Nemotron(client=FakeClient(script), on_call=calls.append, model_deep="D", model_fast="F", backoff=0, **kw)
    return llm, calls


SCHEMA = {"required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
ERR = openai.InternalServerError("boom", response=httpx.Response(500, request=httpx.Request("POST", "http://x")),
                                 body=None)


def test_extract_and_strip():
    assert strip_reasoning('<think>x {"a":1}</think> hi') == "hi"
    assert extract_json('<think>{"bad": 0}</think>Sure: {"a": {"b": "}"}} trailing') == {"a": {"b": "}"}}
    assert extract_json('reasoning... </think>{"z": 2}') == {"z": 2}
    with pytest.raises(ValueError):
        extract_json("nothing")


def test_ok_call_emits_modelcall(tmp_path):
    log = tmp_path / "p.jsonl"
    llm, calls = mk(['{"ok": true}'], prompt_log=log)
    assert asyncio.run(llm.json("p", "s", "u", SCHEMA)) == {"ok": True}
    assert calls[0].model == "prov/F" and calls[0].ok and calls[0].prompt_tokens == 3 and calls[0].request_sha
    assert "response_text" in log.read_text()
    assert llm.stats()["tokens"] == 5


def test_invalid_retry_then_escalate():
    llm, calls = mk(['{"ok": "x"}', "no json", '{"ok": false}'])
    assert asyncio.run(llm.json("p", "s", "u", SCHEMA)) == {"ok": False}
    assert [c.tier for c in calls] == ["fast", "fast", "deep"]
    assert calls[-1].escalated and calls[-1].model == "prov/D" and not calls[0].ok


def test_transient_retry_and_failure():
    llm, calls = mk([ERR, '{"ok": true}'])
    assert asyncio.run(llm.json("p", "s", "u", SCHEMA)) == {"ok": True}
    assert [c.ok for c in calls] == [False, True]
    llm, _ = mk([ERR, ERR, ERR])
    with pytest.raises(LLMError):
        asyncio.run(llm.json("p", "s", "u"))


def test_no_models():
    llm = Nemotron(client=FakeClient([]), model_deep="", model_fast="")
    with pytest.raises(LLMError, match="LS_MODEL"):
        asyncio.run(llm.json("p", "s", "u"))
