from __future__ import annotations

"""Optional WeChat Official Account API adapter.

This adapter is intentionally scoped to authorized official accounts controlled by the
operator. It is not a general public WeChat article search interface.

Expected use:
1. Store an authorized account in `wechat_authorized_accounts`.
2. Keep its app secret in an environment variable named by `appsecret_env`.
3. Call the official token endpoint and `freepublish/batchget` to sync published items.
4. Convert returned articles into the same ParsedArticle pipeline used by public URLs.
"""

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from .wechat_articles import ParsedArticle, normalize_wechat_url, parse_datetime, strip_tags

API_BASE = "https://api.weixin.qq.com/cgi-bin"


class WechatOfficialApiError(RuntimeError):
    pass


def _json_request(url: str, payload: dict[str, Any] | None = None, timeout: int = 10) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise WechatOfficialApiError(f"invalid JSON response: {body[:200]}") from exc
    if isinstance(result, dict) and result.get("errcode") not in (None, 0):
        raise WechatOfficialApiError(f"WeChat API error {result.get('errcode')}: {result.get('errmsg')}")
    return result


def get_access_token(appid: str, appsecret: str, timeout: int = 10) -> str:
    params = urllib.parse.urlencode({"grant_type": "client_credential", "appid": appid, "secret": appsecret})
    result = _json_request(f"{API_BASE}/token?{params}", timeout=timeout)
    token = result.get("access_token")
    if not token:
        raise WechatOfficialApiError("access_token missing from WeChat response")
    return str(token)


def get_access_token_from_env(appid: str, appsecret_env: str, timeout: int = 10) -> str:
    secret = os.getenv(appsecret_env)
    if not secret:
        raise WechatOfficialApiError(f"environment variable {appsecret_env} is not set")
    return get_access_token(appid, secret, timeout=timeout)


def batch_get_published(access_token: str, offset: int = 0, count: int = 20, no_content: int = 0, timeout: int = 10) -> dict[str, Any]:
    if count < 1 or count > 20:
        raise ValueError("count must be between 1 and 20")
    url = f"{API_BASE}/freepublish/batchget?access_token={urllib.parse.quote(access_token)}"
    payload = {"offset": offset, "count": count, "no_content": no_content}
    return _json_request(url, payload=payload, timeout=timeout)


def _pick_article_url(item: dict[str, Any]) -> str:
    candidates = [item.get("url"), item.get("content_url"), item.get("source_url"), item.get("article_url")]
    for value in candidates:
        if value:
            return normalize_wechat_url(str(value))
    return ""


def convert_freepublish_items(account_name: str, items: list[dict[str, Any]]) -> list[ParsedArticle]:
    """Convert freepublish records into ParsedArticle objects when content is present.

    WeChat response structures vary by account type and endpoint version. This converter
    handles the common `content.news_item` shape and ignores entries that do not contain
    an article URL or HTML/content text.
    """
    parsed: list[ParsedArticle] = []
    for record in items:
        content = record.get("content") or {}
        news_items = content.get("news_item") or record.get("news_item") or []
        if isinstance(news_items, dict):
            news_items = [news_items]
        for item in news_items:
            if not isinstance(item, dict):
                continue
            url = _pick_article_url(item)
            title = str(item.get("title") or "未命名公众号文章")
            html_content = str(item.get("content") or "")
            plain = strip_tags(html_content) or str(item.get("digest") or "")
            if not url and not plain:
                continue
            publish_time = item.get("publish_time") or record.get("publish_time") or item.get("create_time") or record.get("create_time")
            canonical = url or f"wechat-official-api://{account_name}/{record.get('article_id') or record.get('publish_id') or title}"
            parsed.append(
                ParsedArticle(
                    canonical_url=canonical,
                    original_url=url or canonical,
                    title=title,
                    account_name=account_name,
                    account_biz=str(record.get("account_biz") or ""),
                    digest=str(item.get("digest") or ""),
                    cover_url=str(item.get("thumb_url") or item.get("cover_url") or ""),
                    publish_at=parse_datetime(str(publish_time)) if publish_time else None,
                    content_text=plain,
                    content_html=html_content,
                    images=[],
                    content_hash="",
                )
            )
    return parsed
