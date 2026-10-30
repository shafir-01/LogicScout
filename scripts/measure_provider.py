"""Measure Nebius Token Factory (Nemotron) and Tavily behaviour; raw results go to data/measurements/.

Usage: uv run python scripts/measure_provider.py [section ...]
Sections: models chat stream json schema tools errors concurrency tavily runs   (default: all)
Env: NEBIUS_API_KEY, TAVILY_API_KEY (from .env). Call counts are small by design (see N_* constants).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "measurements"
load_dotenv(ROOT / ".env")
BASE = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/").rstrip("/")
KEY = os.getenv("NEBIUS_API_KEY", "")
TKEY = os.getenv("TAVILY_API_KEY", "")
MODELS = {
    "nano": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "super": "nvidia/nemotron-3-super-120b-a12b",
    "ultra": "nvidia/Nemotron-3-Ultra-550b-a55b",
}
N_LAT = {"nano": 10, "super": 10, "ultra": 10}
N_STREAM = 5
N_JSON = {"nano": 10, "super": 10, "ultra": 5}
RL_HEADERS = ("ratelimit", "retry-after", "x-request-id", "x-ratelimit")
SMALL = [{"role": "user", "content": "Reply with exactly the word: pong"}]
JSON_TASK = [
    {"role": "system", "content": "Return only a JSON object."},
    {"role": "user", "content": 'A valve has pressure 4.2 bar and opens at 5 bar. Return JSON {"will_open": bool, "margin_bar": number, "reason": string}.'},
]


def hdrs(r: httpx.Response) -> dict:
    return {k: v for k, v in r.headers.items() if any(s in k.lower() for s in RL_HEADERS)}


def post(client, body, model=None, path="/chat/completions"):
    t = time.perf_counter()
    try:
        r = client.post(BASE + path, json=body, headers={"Authorization": f"Bearer {KEY}"})
        ms = (time.perf_counter() - t) * 1000
        try:
            j = r.json()
        except Exception:
            j = {"_raw": r.text[:500]}
        return {"model": model, "status": r.status_code, "ms": round(ms, 1), "headers": hdrs(r), "body": j}
    except Exception as e:
        return {"model": model, "status": None, "ms": round((time.perf_counter() - t) * 1000, 1), "exc": repr(e)}


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], 1) if xs else None


def dist(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": round(min(xs), 1), "p50": pct(xs, .5), "p95": pct(xs, .95), "max": round(max(xs), 1),
            "mean": round(statistics.mean(xs), 1)}


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    print("saved", name)


def msg(rec):
    try:
        return rec["body"]["choices"][0]["message"]
    except Exception:
        return {}


def sec_models(c):
    r = c.get(BASE + "/models", headers={"Authorization": f"Bearer {KEY}"}, params={"verbose": "true"})
    j = r.json()
    data = j.get("data", [])
    ids = [m.get("id") for m in data]
    nem = [m for m in data if "nemotron" in str(m.get("id", "")).lower()]
    keys = sorted({k for m in data for k in m})
    save("models", {"status": r.status_code, "headers": hdrs(r), "count": len(ids), "fields_seen": keys,
                    "nemotron": nem, "our_ids_listed": {k: v in ids for k, v in MODELS.items()},
                    "first_entry": (data or [None])[0]})


def sec_chat(c):
    out = {}
    for k, m in MODELS.items():
        recs = [post(c, {"model": m, "messages": SMALL, "max_tokens": 512}, m) for _ in range(N_LAT[k])]
        out[k] = {"model": m, "calls": recs, "latency_ms": dist([r["ms"] for r in recs if r["status"] == 200]),
                  "ok": sum(r["status"] == 200 for r in recs), "n": len(recs)}
    save("chat_latency", out)


def sec_stream(c):
    out = {}
    for k, m in MODELS.items():
        recs = []
        for _ in range(N_STREAM):
            t = time.perf_counter()
            first = first_content = usage = None
            chunks = 0
            txt = reasoning = ""
            try:
                with c.stream("POST", BASE + "/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                              json={"model": m, "messages": SMALL, "max_tokens": 512, "stream": True,
                                    "stream_options": {"include_usage": True}}) as r:
                    status = r.status_code
                    for line in r.iter_lines():
                        if not line.startswith("data:") or line.strip() == "data: [DONE]":
                            continue
                        if first is None:
                            first = (time.perf_counter() - t) * 1000
                        d = json.loads(line[5:])
                        chunks += 1
                        usage = d.get("usage") or usage
                        for ch in d.get("choices", []):
                            dl = ch.get("delta", {})
                            reasoning += dl.get("reasoning_content") or dl.get("reasoning") or ""
                            if dl.get("content"):
                                if first_content is None:
                                    first_content = (time.perf_counter() - t) * 1000
                                txt += dl["content"]
                recs.append({"status": status, "ttft_ms": first, "first_content_ms": first_content,
                             "total_ms": (time.perf_counter() - t) * 1000, "chunks": chunks, "usage": usage,
                             "content": txt[:200], "reasoning_chars": len(reasoning)})
            except Exception as e:
                recs.append({"exc": repr(e)})
        good = [r for r in recs if r.get("ttft_ms")]
        out[k] = {"model": m, "calls": recs, "ttft_ms": dist([r["ttft_ms"] for r in good]),
                  "first_content_ms": dist([r["first_content_ms"] for r in good if r.get("first_content_ms")]),
                  "usage_in_stream": sum(bool(r.get("usage")) for r in recs)}
    save("stream", out)


def valid_obj(s):
    try:
        return isinstance(json.loads(s), dict)
    except Exception:
        return False


def sec_json(c):
    out = {}
    for k, m in MODELS.items():
        res = {}
        for mode, rf in (("json_object", {"type": "json_object"}), ("prompt_only", None)):
            recs = []
            for _ in range(N_JSON[k]):
                body = {"model": m, "messages": JSON_TASK, "max_tokens": 2048}
                if rf:
                    body["response_format"] = rf
                recs.append(post(c, body, m))
            cont = [msg(r).get("content") or "" for r in recs]
            res[mode] = {"calls": recs, "n": len(recs), "http_ok": sum(r["status"] == 200 for r in recs),
                         "valid_json": sum(valid_obj(x) for x in cont),
                         "think_tag_in_content": sum(("<think" in x or "</think" in x) for x in cont),
                         "reasoning_field_present": sum(bool(msg(r).get("reasoning_content") or msg(r).get("reasoning")) for r in recs),
                         "finish_reasons": [r["body"]["choices"][0].get("finish_reason") if r["status"] == 200 else None for r in recs],
                         "latency_ms": dist([r["ms"] for r in recs if r["status"] == 200]),
                         "completion_tokens": [r["body"].get("usage", {}).get("completion_tokens") if r["status"] == 200 else None for r in recs]}
        out[k] = {"model": m, **res}
    save("json_mode", out)


SCHEMA = {"type": "object", "properties": {"will_open": {"type": "boolean"}, "margin_bar": {"type": "number"},
                                           "reason": {"type": "string"}},
          "required": ["will_open", "margin_bar", "reason"], "additionalProperties": False}


def sec_schema(c):
    out = {}
    for k, m in MODELS.items():
        recs = [post(c, {"model": m, "messages": JSON_TASK, "max_tokens": 2048,
                         "response_format": {"type": "json_schema", "json_schema": {"name": "valve", "strict": True, "schema": SCHEMA}}}, m)
                for _ in range(3)]
        conf = 0
        for r in recs:
            s = msg(r).get("content") or ""
            if valid_obj(s) and set(json.loads(s)) == set(SCHEMA["required"]):
                conf += 1
        out[k] = {"model": m, "calls": recs, "http_ok": sum(r["status"] == 200 for r in recs), "schema_conformant": conf, "n": len(recs)}
    save("json_schema", out)


TOOL = {"type": "function", "function": {"name": "get_pressure", "description": "Read the pressure of a valve in bar.",
        "parameters": {"type": "object", "properties": {"valve_id": {"type": "string"}}, "required": ["valve_id"]}}}


def sec_tools(c):
    out = {}
    for k, m in MODELS.items():
        recs = [post(c, {"model": m, "max_tokens": 2048, "tools": [TOOL],
                         "messages": [{"role": "user", "content": "What is the pressure of valve V-17? Use the tool."}]}, m) for _ in range(3)]
        called = args_ok = 0
        for r in recs:
            tc = msg(r).get("tool_calls") or []
            called += bool(tc)
            try:
                args_ok += bool(tc) and "valve_id" in json.loads(tc[0]["function"]["arguments"])
            except Exception:
                pass
        out[k] = {"model": m, "calls": recs, "http_ok": sum(r["status"] == 200 for r in recs), "tool_called": called,
                  "args_valid": args_ok, "n": len(recs)}
    save("tool_calling", out)


def sec_errors(c):
    m = MODELS["nano"]
    cases = {
        "invalid_model": {"model": "nvidia/does-not-exist", "messages": SMALL},
        "ultra_lowercased_id": {"model": MODELS["ultra"].lower(), "messages": SMALL, "max_tokens": 16},
        "missing_messages": {"model": m},
        "bad_temperature": {"model": m, "messages": SMALL, "temperature": 9},
        "negative_max_tokens": {"model": m, "messages": SMALL, "max_tokens": -5},
        "bad_role": {"model": m, "messages": [{"role": "wizard", "content": "x"}]},
        "bad_response_format": {"model": m, "messages": SMALL, "response_format": {"type": "nonsense"}},
        "max_tokens_1": {"model": m, "messages": SMALL, "max_tokens": 1},
    }
    out = {n: post(c, b, b.get("model")) for n, b in cases.items()}
    r = c.post(BASE + "/chat/completions", json={"model": m, "messages": SMALL}, headers={"Authorization": "Bearer bad"})
    out["bad_api_key"] = {"status": r.status_code, "body": r.text[:400]}
    r = c.post(BASE + "/chat/completions", content="{not json", headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    out["malformed_json_body"] = {"status": r.status_code, "body": r.text[:400]}
    filler = "The quick brown fox jumps over the lazy dog. " * 4500  # ~200k chars
    out["long_prompt_200k_chars"] = post(c, {"model": m, "messages": [{"role": "user", "content": filler + "\nSay ok."}], "max_tokens": 16}, m)
    save("errors", out)


def sec_concurrency(c):
    out = {}
    for k, m in MODELS.items():
        def one(_, m=m):
            with httpx.Client(timeout=300) as cc:
                return post(cc, {"model": m, "messages": SMALL, "max_tokens": 512}, m)
        t = time.perf_counter()
        with ThreadPoolExecutor(5) as ex:
            recs = list(ex.map(one, range(5)))
        out[k] = {"model": m, "wall_ms": round((time.perf_counter() - t) * 1000, 1), "calls": recs,
                  "statuses": [r["status"] for r in recs], "latency_ms": dist([r["ms"] for r in recs if r["status"] == 200])}
    save("concurrency", out)


def tav(c, body):
    t = time.perf_counter()
    r = c.post("https://api.tavily.com/search", json=body, headers={"Authorization": f"Bearer {TKEY}"})
    ms = (time.perf_counter() - t) * 1000
    try:
        j = r.json()
    except Exception:
        j = {"_raw": r.text[:300]}
    return {"status": r.status_code, "ms": round(ms, 1), "headers": hdrs(r), "body": j}


def sec_tavily(c):
    qs = ["how do token bucket rate limiters work", "PID controller anti-windup", "queueing theory M/M/1 utilization",
          "thermal throttling in datacenter GPUs", "exponential backoff with jitter"]
    out = {"depth": {}}
    for depth in ("basic", "advanced"):
        recs = [tav(c, {"query": q, "search_depth": depth, "max_results": 5, "topic": "general"}) for q in qs]
        results = [x for r in recs if r["status"] == 200 for x in r["body"].get("results", [])]
        out["depth"][depth] = {"calls": recs, "latency_ms": dist([r["ms"] for r in recs if r["status"] == 200]),
                               "results": len(results), "with_published_date": sum(bool(x.get("published_date")) for x in results),
                               "response_keys": sorted({k for r in recs if r["status"] == 200 for k in r["body"]}),
                               "usage": [r["body"].get("usage") for r in recs if r["status"] == 200]}
    nq = [tav(c, {"query": q, "search_depth": "basic", "max_results": 5, "topic": "news"}) for q in qs[:3]]
    nres = [x for r in nq if r["status"] == 200 for x in r["body"].get("results", [])]
    out["news_topic"] = {"calls": nq, "results": len(nres), "with_published_date": sum(bool(x.get("published_date")) for x in nres)}
    out["usage_flag"] = tav(c, {"query": qs[0], "include_usage": True, "max_results": 3})
    out["errors"] = {
        "bad_depth": tav(c, {"query": "x", "search_depth": "ultra"}),
        "max_results_999": tav(c, {"query": "x", "max_results": 999}),
        "empty_query": tav(c, {"query": ""}),
        "bad_topic": tav(c, {"query": "x", "topic": "weather"}),
    }
    r = c.post("https://api.tavily.com/search", json={"query": "x"}, headers={"Authorization": "Bearer bad"})
    out["errors"]["bad_key"] = {"status": r.status_code, "body": r.text[:300]}
    save("tavily", out)


def sec_runs(c):
    stats = {}
    for f in sorted((ROOT / "data" / "runs").glob("*/events.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("kind") == "model.call":
                stats.setdefault(e["data"]["model"], []).append({**e["data"], "run": e["run_id"]})
    out = {}
    for m, calls in stats.items():
        out[m] = {"calls": len(calls), "ok": sum(x["ok"] for x in calls), "failed": [x["error"] for x in calls if not x["ok"]],
                  "escalated_flag": sum(x["escalated"] for x in calls),
                  "latency_ok_ms": dist([x["latency_ms"] for x in calls if x["ok"]]),
                  "latency_all_ms": dist([x["latency_ms"] for x in calls]),
                  "completion_tokens": dist([x["completion_tokens"] for x in calls if x["completion_tokens"]]),
                  "completion_tokens_at_8192": sum(x["completion_tokens"] == 8192 for x in calls),
                  "runs": sorted({x["run"] for x in calls}), "purposes": sorted({x["purpose"] for x in calls})}
    save("runs_model_calls", out)


SECTIONS = {k[4:]: v for k, v in list(globals().items()) if k.startswith("sec_")}

if __name__ == "__main__":
    if not KEY or not TKEY:
        sys.exit("NEBIUS_API_KEY and TAVILY_API_KEY must be set in .env")
    want = sys.argv[1:] or list(SECTIONS)
    with httpx.Client(timeout=300) as client:
        for s in want:
            SECTIONS[s](client)
