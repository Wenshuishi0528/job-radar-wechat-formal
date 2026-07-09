from __future__ import annotations

"""Optional external discovery adapters for WeChat article candidates.

These adapters are not wired into the default API path. They exist so a production
worker can add paid or authorized discovery providers without changing the core
article parser and storage model.
"""

import json
import os
import urllib.request
from dataclasses import asdict
from typing import Any

from .wechat_articles import ArticleCandidate, normalize_wechat_url

MP_DOMAIN = "mp.weixin.qq.com"


class ExternalSearchError(RuntimeError):
    pass


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ExternalSearchError(f"invalid JSON from external search provider: {body[:200]}") from exc


def _safe_max_results(max_results: int) -> int:
    return max(1, min(max_results, 10))


def firecrawl_search_candidates(keyword: str, max_results: int = 5, time_filter: str = "qdr:m") -> list[dict[str, Any]]:
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        raise ExternalSearchError("FIRECRAWL_API_KEY is not set")
    payload = {
        "query": f"site:{MP_DOMAIN}/s {keyword}",
        "limit": _safe_max_results(max_results),
        "includeDomains": [MP_DOMAIN],
        "tbs": time_filter,
    }
    result = _post_json("https://api.firecrawl.dev/v2/search", payload, {"Authorization": f"Bearer {api_key}"})
    rows = result.get("data") or result.get("results") or []
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = normalize_wechat_url(str(row.get("url") or row.get("link") or ""))
        if MP_DOMAIN not in url:
            continue
        candidate = ArticleCandidate(
            url=url,
            title=str(row.get("title") or ""),
            digest=str(row.get("description") or row.get("content") or ""),
            provider="firecrawl_search",
            source_query=keyword,
        )
        candidates.append(asdict(candidate))
    return candidates


def tavily_search_candidates(keyword: str, max_results: int = 5, time_range: str = "month") -> list[dict[str, Any]]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ExternalSearchError("TAVILY_API_KEY is not set")
    payload = {
        "api_key": api_key,
        "query": f"site:{MP_DOMAIN}/s {keyword}",
        "max_results": _safe_max_results(max_results),
        "include_raw_content": False,
        "include_answer": False,
        "include_domains": [MP_DOMAIN],
        "time_range": time_range,
    }
    result = _post_json("https://api.tavily.com/search", payload, {})
    rows = result.get("results") or []
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = normalize_wechat_url(str(row.get("url") or ""))
        if MP_DOMAIN not in url:
            continue
        candidate = ArticleCandidate(
            url=url,
            title=str(row.get("title") or ""),
            digest=str(row.get("content") or ""),
            provider="tavily_search",
            source_query=keyword,
            score=float(row.get("score") or 0.0),
        )
        candidates.append(asdict(candidate))
    return candidates
