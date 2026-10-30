import httpx
import pytest

from logicscout.briefing import TavilyClient, TavilyError, brief, check
from logicscout.contracts import ActionSpec, FieldSpec, Hypothesis, Objective, Rule, Theory, WorldManual
from logicscout.logbook import Logbook

PAYLOAD = {
    "results": [
        {"url": "https://a.example/doc", "title": "A", "content": "Queues drop packets when full.", "score": 0.9, "published_date": "2025-01-01"},
        {"url": "https://b.example/doc", "title": "B", "content": "Retries add latency.", "score": 0.5},
    ],
    "usage": {"credits": 1},
}


def mock(handler):
    return httpx.MockTransport(handler)


async def test_search_ok_and_stats():
    seen = {}

    def h(req):
        seen["auth"] = req.headers["authorization"]
        seen["body"] = req.read().replace(b" ", b"")
        return httpx.Response(200, json=PAYLOAD)

    c = TavilyClient("tvly-x", transport=mock(h))
    res = await c.search("message queue", max_results=2)
    assert [s.url for s in res] == ["https://a.example/doc", "https://b.example/doc"]
    assert res[0].published_date == "2025-01-01" and res[0].retrieved_at
    assert seen["auth"] == "Bearer tvly-x" and b'"max_results":2' in seen["body"]
    st = c.stats()
    assert st["calls"] == 1 and st["results"] == 2 and st["credits"] == 1


async def test_missing_key():
    with pytest.raises(TavilyError, match="TAVILY_API_KEY"):
        await TavilyClient("", transport=mock(lambda r: httpx.Response(200))).search("q")


async def test_retry_then_ok_and_hard_fail():
    n = {"i": 0}

    def flaky(req):
        n["i"] += 1
        return httpx.Response(500) if n["i"] < 2 else httpx.Response(200, json=PAYLOAD)

    c = TavilyClient("k", transport=mock(flaky), backoff=0)
    assert len(await c.search("q")) == 2 and n["i"] == 2
    bad = TavilyClient("k", transport=mock(lambda r: httpx.Response(401, text="no")), backoff=0)
    with pytest.raises(TavilyError, match="401"):
        await bad.search("q")
    assert bad.stats()["failed"] == 1


MANUAL = WorldManual(
    world_id="w", title="T", domain="message relay", summary="s",
    actions=[ActionSpec(name="send")],
    observations=[FieldSpec(name="queue", type="int"), FieldSpec(name="dropped", type="int")],
    objectives=[Objective(id="o", text="x", success="obs.queue > 0", horizon=5)], probe_budget=5,
    briefing_topics=["how message queues behave when full"],
)


class FakeLLM:
    def __init__(self, out):
        self.out, self.calls = out, []

    async def json(self, purpose, system, user, schema=None, tier="fast"):
        self.calls.append((purpose, tier, user))
        return self.out


async def test_brief_builds_cited_hypotheses():
    llm = FakeLLM({"claims": [
        {"claim": "Full queues drop new items", "sources": [1],
         "rule": {"action": "send", "when": "obs.queue >= 3", "effects": {"dropped": "obs.dropped + 1"}}},
        {"claim": "bad field", "sources": [1], "rule": {"action": "send", "effects": {"nope": "1"}}},
        {"claim": "no source", "sources": [], "rule": {"action": "send", "effects": {"queue": "0"}}},
    ]})
    log = Logbook("r")
    client = TavilyClient("k", transport=mock(lambda r: httpx.Response(200, json=PAYLOAD)))
    hyps = await brief(MANUAL, llm, log, client=client)
    assert len(hyps) == 1
    h = hyps[0]
    assert h.source == "briefing" and h.rule.source == "briefing" and h.rule.citations == ["https://a.example/doc"]
    assert llm.calls[0][:2] == ("briefing_priors", "fast")
    assert "Queues drop packets" in llm.calls[0][2]
    kinds = [e.kind for e in log.events]
    assert kinds.count("briefing.query") == 1 and kinds.count("briefing.source") == 2 and kinds.count("briefing.claim") == 1
    assert next(e for e in log.events if e.kind == "briefing.query").data["query"] == MANUAL.briefing_topics[0]


async def test_brief_no_sources():
    client = TavilyClient("k", transport=mock(lambda r: httpx.Response(200, json={"results": []})))
    llm = FakeLLM({})
    assert await brief(MANUAL, llm, Logbook("r"), client=client) == [] and not llm.calls


def _hyp(i, st):
    return Hypothesis(id=i, statement=i, status=st, source="briefing",
                      rule=Rule(id=i, statement=i, effects={"queue": "1"}, citations=["u"]))


def test_check_maps_status():
    res = check([_hyp("a", "supported"), _hyp("b", "refuted"), _hyp("c", "open")], Theory(world_id="w"))
    assert [r["status"] for r in res] == ["confirmed", "contradicted", "untested"]
    th = Theory(world_id="w", rules=[Rule(id="c", statement="c", status="refuted")])
    assert check([_hyp("c", "open")], th)[0]["status"] == "contradicted"
