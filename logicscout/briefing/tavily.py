"""Async Tavily search client (POST https://api.tavily.com/search, Bearer auth)."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from logicscout import config

TAVILY_URL = "https://api.tavily.com/search"


class TavilyError(RuntimeError):
    pass


class Source(BaseModel):
    url: str
    title: str = ""
    content: str = ""
    score: float = 0.0
    published_date: str | None = None
    retrieved_at: str = ""


class TavilyClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 20.0,
        retries: int = 2,
        backoff: float = 0.5,
        url: str = TAVILY_URL,
    ) -> None:
        self.api_key = config.TAVILY_API_KEY if api_key is None else api_key
        self.url = url
        self.retries = retries
        self.backoff = backoff
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout)
        self._calls: list[dict[str, Any]] = []

    async def aclose(self) -> None:
        await self._http.aclose()

    async def search(self, query: str, **params: Any) -> list[Source]:
        if not self.api_key:
            raise TavilyError("TAVILY_API_KEY is not set; add it to .env (free key at https://app.tavily.com)")
        body = {
            "search_depth": "basic", "max_results": 5, "include_published_date": True, "include_usage": True,
            **params, "query": query,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last = ""
        attempt = 0
        for attempt in range(self.retries + 1):
            t0 = time.perf_counter()
            try:
                r = await self._http.post(self.url, json=body, headers=headers)
            except httpx.HTTPError as e:
                last = f"{type(e).__name__}: {e}"
            else:
                if r.status_code == 200:
                    data = r.json()
                    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    out = [
                        Source(
                            url=x["url"], title=x.get("title") or "", content=x.get("content") or "",
                            score=float(x.get("score") or 0.0), published_date=x.get("published_date"), retrieved_at=now,
                        )
                        for x in data.get("results", [])
                        if x.get("url")
                    ]
                    self._calls.append({
                        "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "results": len(out),
                        "credits": (data.get("usage") or {}).get("credits"), "ok": True, "attempts": attempt + 1,
                    })
                    return out
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code in (400, 401, 422, 432, 433):
                    break  # not retryable
                if r.status_code == 429:
                    await asyncio.sleep(min(float(r.headers.get("Retry-After", self.backoff)), 5.0))
                    continue
            if attempt < self.retries:
                await asyncio.sleep(self.backoff * (2**attempt))
        self._calls.append({"latency_ms": 0.0, "results": 0, "credits": None, "ok": False, "attempts": attempt + 1})
        raise TavilyError(f"Tavily search failed: {last}")

    def stats(self) -> dict[str, Any]:
        ok = [c for c in self._calls if c["ok"]]
        lat = sorted(c["latency_ms"] for c in ok)
        credits = [c["credits"] for c in ok if c["credits"] is not None]
        return {
            "provider": "tavily",
            "calls": len(self._calls),
            "failed": len(self._calls) - len(ok),
            "results": sum(c["results"] for c in ok),
            "credits": sum(credits) if credits else None,
            "latency_ms_avg": round(sum(lat) / len(lat), 1) if lat else None,
            "latency_ms_p50": lat[len(lat) // 2] if lat else None,
            "latency_ms_max": lat[-1] if lat else None,
        }
