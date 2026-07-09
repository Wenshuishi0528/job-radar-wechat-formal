from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Iterable

from .database import get_connection

PARSER_VERSION = "wechat_parser_v1"
DEFAULT_MAX_AGE_DAYS = 45
MP_HOST = "mp.weixin.qq.com"
WECHAT_URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com/(?:s/[^\s\"'<>#]+|s\?[^\s\"'<>#]+)", re.I)
USER_AGENT = os.getenv(
    "JOB_RADAR_USER_AGENT",
    "JobRadar/0.2 public-WeChat-article-fetcher no-login-cookie contact=operator",
)

JOB_SIGNAL_KEYWORDS = [
    "校招", "校园招聘", "秋招", "春招", "提前批", "补录", "实习", "暑期实习", "网申", "内推",
    "招聘", "岗位", "宣讲会", "空中宣讲", "应届", "毕业生", "留学生", "海归", "海外学子",
]
LOW_QUALITY_KEYWORDS = [
    "保offer", "保录", "付费内推", "收费内推", "培训贷", "招转培", "加微信领取", "私信领取",
    "0基础转码", "高薪就业班", "包过", "刷流水", "贷款", "兼职日结",
]
SOURCE_RANK = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class ArticleCandidate:
    url: str
    title: str = ""
    account_name: str = ""
    digest: str = ""
    cover_url: str = ""
    publish_at: str | None = None
    provider: str = "unknown"
    source_query: str = ""
    score: float = 0.0
    raw: dict[str, Any] | None = None


@dataclass
class ParsedArticle:
    canonical_url: str
    original_url: str
    title: str
    account_name: str = ""
    account_biz: str = ""
    digest: str = ""
    cover_url: str = ""
    publish_at: str | None = None
    content_text: str = ""
    content_html: str = ""
    images: list[str] | None = None
    content_hash: str = ""


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "canvas"}:
            self.skip_depth += 1
        if tag in {"p", "div", "section", "br", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "canvas"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"p", "div", "section", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        data = data.strip()
        if data:
            self.parts.append(data)

    def text(self) -> str:
        return normalize_space(" ".join(self.parts))


def normalize_space(value: str | None) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"[\t\r\f\v]+", " ", value)
    value = re.sub(r"\s*\n\s*", "\n", value)
    value = re.sub(r"[ ]{2,}", " ", value)
    return value.strip()


def strip_tags(value: str | None) -> str:
    parser = TextExtractor()
    parser.feed(value or "")
    return parser.text()


def parse_datetime(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip().strip("'\"")
    if not raw:
        return None
    if raw.isdigit():
        timestamp = int(raw)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        try:
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError):
            return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y年%m月%d日 %H:%M"]:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    match = re.search(r"(20\d{2})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})", raw)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d} 00:00:00"
    return None


def normalize_wechat_url(url: str) -> str:
    url = html.unescape((url or "").strip())
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    parsed = urllib.parse.urlparse(url)
    if "sogou.com" in parsed.netloc and parsed.path.startswith("/link"):
        qs = urllib.parse.parse_qs(parsed.query)
        for key in ["url", "target", "redirect"]:
            if qs.get(key):
                nested = urllib.parse.unquote(qs[key][0])
                if MP_HOST in nested:
                    return normalize_wechat_url(nested)
    if parsed.netloc != MP_HOST and MP_HOST in url:
        match = WECHAT_URL_RE.search(url)
        if match:
            return normalize_wechat_url(match.group(0))
    if parsed.netloc != MP_HOST:
        return url.split("#", 1)[0]
    if parsed.path.startswith("/s/"):
        return urllib.parse.urlunparse(("https", MP_HOST, parsed.path.rstrip("/"), "", "", ""))
    if parsed.path == "/s":
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        keep = []
        for key in ["__biz", "mid", "idx", "sn"]:
            if qs.get(key):
                keep.append((key, qs[key][0]))
        if keep:
            return urllib.parse.urlunparse(("https", MP_HOST, "/s", "", urllib.parse.urlencode(keep), ""))
    return urllib.parse.urlunparse(("https", MP_HOST, parsed.path, "", parsed.query, ""))


def is_wechat_article_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(normalize_wechat_url(url))
    return parsed.netloc == MP_HOST and (parsed.path == "/s" or parsed.path.startswith("/s/"))


def extract_first(patterns: Iterable[str], text: str, flags: int = re.S) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return html.unescape(match.group(1)).strip().strip("'\"")
    return ""


def extract_meta(html_text: str, names: Iterable[str]) -> str:
    for name in names:
        patterns = [
            rf'<meta[^>]+property=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']{re.escape(name)}["\']',
            rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']{re.escape(name)}["\']',
        ]
        value = extract_first(patterns, html_text, flags=re.I | re.S)
        if value:
            return value
    return ""


def extract_element_by_id(html_text: str, element_id: str) -> str:
    pattern = rf'<(?P<tag>[a-zA-Z0-9]+)[^>]+id=["\']{re.escape(element_id)}["\'][^>]*>(?P<body>.*?)</(?P=tag)>'
    match = re.search(pattern, html_text, re.I | re.S)
    return match.group("body") if match else ""


def extract_images(content_html: str) -> list[str]:
    images: list[str] = []
    for tag in re.findall(r"<img\b[^>]*>", content_html or "", flags=re.I | re.S):
        url = extract_first([r'data-src=["\']([^"\']+)["\']', r'src=["\']([^"\']+)["\']'], tag, flags=re.I | re.S)
        if url and not url.startswith("data:"):
            if url.startswith("//"):
                url = "https:" + url
            if url not in images:
                images.append(html.unescape(url))
    return images


def parse_wechat_article_html(html_text: str, original_url: str) -> ParsedArticle:
    title = normalize_space(strip_tags(extract_element_by_id(html_text, "activity-name")))
    if not title:
        title = extract_first([r"var\s+msg_title\s*=\s*'([^']*)'", r'var\s+msg_title\s*=\s*"([^"]*)"'], html_text)
    if not title:
        title = extract_meta(html_text, ["og:title", "twitter:title"])
    if not title:
        title = normalize_space(strip_tags(extract_first([r"<title[^>]*>(.*?)</title>"], html_text, flags=re.I | re.S))).replace("微信公众平台", "").strip()

    account_html = extract_element_by_id(html_text, "js_name")
    account_name = normalize_space(strip_tags(account_html))
    if not account_name:
        account_name = extract_first([r"var\s+nickname\s*=\s*htmlDecode\('([^']*)'\)", r"var\s+nickname\s*=\s*'([^']*)'", r'var\s+nickname\s*=\s*"([^"]*)"'], html_text)
    if not account_name:
        account_name = extract_meta(html_text, ["author", "og:article:author"])

    digest = extract_first([r"var\s+msg_desc\s*=\s*'([^']*)'", r'var\s+msg_desc\s*=\s*"([^"]*)"'], html_text) or extract_meta(html_text, ["description", "og:description"])
    cover_url = extract_first([r"var\s+msg_cdn_url\s*=\s*'([^']*)'", r'var\s+msg_cdn_url\s*=\s*"([^"]*)"'], html_text) or extract_meta(html_text, ["og:image", "twitter:image"])
    if cover_url.startswith("//"):
        cover_url = "https:" + cover_url
    publish_at = parse_datetime(extract_first([
        r"var\s+ct\s*=\s*['\"]?(\d{10,13})['\"]?",
        r"oriCreateTime\s*=\s*['\"]?(\d{10,13})['\"]?",
        r"publish_time\s*=\s*['\"]([^'\"]+)['\"]",
        r"ct\s*:\s*['\"]?(\d{10,13})['\"]?",
    ], html_text)) or parse_datetime(strip_tags(extract_element_by_id(html_text, "publish_time")))
    content_html = extract_element_by_id(html_text, "js_content")
    content_text = strip_tags(content_html) if content_html else strip_tags(html_text)
    images = extract_images(content_html)
    account_biz = extract_first([r"var\s+biz\s*=\s*['\"]([^'\"]+)['\"]", r"__biz=([^&\"']+)"], html_text + " " + original_url)
    canonical_url = normalize_wechat_url(extract_meta(html_text, ["og:url"]) or original_url)
    content_hash = hashlib.sha256((title + "\n" + account_name + "\n" + content_text).encode("utf-8", errors="ignore")).hexdigest()
    return ParsedArticle(
        canonical_url=canonical_url,
        original_url=original_url,
        title=normalize_space(title) or "未命名公众号文章",
        account_name=normalize_space(account_name),
        account_biz=account_biz,
        digest=normalize_space(digest),
        cover_url=cover_url,
        publish_at=publish_at,
        content_text=content_text,
        content_html=content_html,
        images=images,
        content_hash=content_hash,
    )


def days_since(value: str | None) -> int | None:
    if not value:
        return None
    raw = str(value).strip()
    for candidate, fmt in [(raw[:19], "%Y-%m-%d %H:%M:%S"), (raw[:10], "%Y-%m-%d")]:
        try:
            dt = datetime.strptime(candidate, fmt)
            return max(0, (datetime.now() - dt).days)
        except ValueError:
            continue
    return None


def freshness_score(publish_at: str | None, max_age_days: int) -> tuple[float, bool]:
    age = days_since(publish_at)
    if age is None:
        return 0.2, False
    if max_age_days <= 0:
        return 1.0, False
    score = max(0.0, 1.0 - min(age, max_age_days * 2) / float(max_age_days * 2))
    return round(score, 4), age > max_age_days


def lookup_account(conn: Any, account_name: str, account_biz: str = "") -> dict[str, Any]:
    row = None
    if account_biz:
        row = conn.execute("SELECT * FROM wechat_accounts WHERE account_biz = ? AND account_biz != ''", (account_biz,)).fetchone()
    if not row and account_name:
        row = conn.execute("SELECT * FROM wechat_accounts WHERE account_name = ?", (account_name,)).fetchone()
    return dict(row) if row else {"trust_level": "C", "is_blocked": 0, "is_allowlisted": 0}


def grade_article(conn: Any, parsed: ParsedArticle, source: str) -> str:
    if source in {"wechat_official_api", "authorized_official_account"}:
        return "S"
    account = lookup_account(conn, parsed.account_name, parsed.account_biz)
    if int(account.get("is_blocked") or 0):
        return "D"
    return account.get("trust_level") or "C"


def quality_score(parsed: ParsedArticle, source_level: str) -> tuple[float, bool, str]:
    text = " ".join([parsed.title, parsed.account_name, parsed.digest, parsed.content_text]).lower()
    score = {"S": 0.82, "A": 0.72, "B": 0.60, "C": 0.42, "D": 0.12}.get(source_level, 0.42)
    reasons: list[str] = []
    blocked = False
    if any(k.lower() in text for k in JOB_SIGNAL_KEYWORDS):
        score += 0.16
        reasons.append("contains_job_signal_keywords")
    else:
        score -= 0.10
        reasons.append("missing_job_signal_keywords")
    for keyword in LOW_QUALITY_KEYWORDS:
        if keyword.lower() in text:
            score -= 0.40
            blocked = True
            reasons.append(f"blocked_keyword:{keyword}")
            break
    if parsed.publish_at:
        score += 0.05
    else:
        score -= 0.05
        reasons.append("missing_publish_at")
    if len(parsed.content_text or "") < 50:
        score -= 0.08
        reasons.append("short_content")
    return max(0.0, min(1.0, round(score, 4))), blocked, ",".join(reasons)


def ensure_wechat_seed_data(conn: Any) -> None:
    ts = utc_now()
    sources = [
        ("Sogou Weixin Search", "sogou_weixin_search", "https://weixin.sogou.com/weixin", "B", 0, 0, 1, 2, "公开搜索入口。默认关闭，启用后限速；不处理验证码，不使用个人 Cookie。"),
        ("WeChat Public Article Page", "wechat_public_article", "https://mp.weixin.qq.com/s/", "A", 1, 0, 0, 12, "已知公开文章 URL 的正文解析入口。"),
        ("WeChat Official Account API", "wechat_official_api", "https://api.weixin.qq.com/cgi-bin/freepublish/", "S", 0, 1, 1, 20, "授权公众号自己的已发布文章列表接口，不是全网搜索接口。"),
        ("Firecrawl Search", "firecrawl_search", "https://api.firecrawl.dev/v2/search", "B", 0, 1, 1, 10, "可选补充搜索 API。"),
        ("Tavily Search", "tavily_search", "https://api.tavily.com/search", "B", 0, 1, 1, 10, "可选补充搜索 API。"),
    ]
    conn.executemany(
        """INSERT OR IGNORE INTO wechat_article_sources(name, source_type, base_url, trust_level, enabled, requires_api_key, supports_freshness, rate_limit_per_minute, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(*source, ts, ts) for source in sources],
    )
    if conn.execute("SELECT COUNT(*) FROM wechat_accounts").fetchone()[0] == 0:
        accounts = [
            ("公司官方招聘", "", json.dumps(["官方招聘", "校园招聘"], ensure_ascii=False), "company_official", "S", 1, 0, "示例账号类型。真实上线时按公众号主体、认证信息和官方链接人工核验。", ts, ts),
            ("高校就业网", "", json.dumps(["就业指导中心", "学生就业"], ensure_ascii=False), "university_career", "A", 1, 0, "高校就业信息来源通常可作为高价值线索。", ts, ts),
            ("求职营销号", "", json.dumps(["内推收费", "保offer"], ensure_ascii=False), "marketing", "D", 0, 1, "示例屏蔽类型。", ts, ts),
        ]
        conn.executemany(
            """INSERT INTO wechat_accounts(account_name, account_biz, account_aliases_json, account_type, trust_level, is_allowlisted, is_blocked, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            accounts,
        )
    if conn.execute("SELECT COUNT(*) FROM wechat_articles").fetchone()[0] == 0:
        demo = ParsedArticle(
            canonical_url="https://mp.weixin.qq.com/s/demo-campus-recruit-2027",
            original_url="https://mp.weixin.qq.com/s/demo-campus-recruit-2027",
            title="云狸科技 2027 届秋招提前批正式启动",
            account_name="公司官方招聘",
            digest="面向 2027 届海内外毕业生，产品、技术、运营岗位开放。",
            cover_url="https://example.com/cover/cloudraccoon.jpg",
            publish_at="2026-07-08 09:30:00",
            content_text="云狸科技 2027 届秋招提前批正式启动。海外毕业时间为 2026 年 9 月至 2027 年 8 月。不设置统一笔试，部分技术岗位可能安排在线题。",
            content_html="<p>云狸科技 2027 届秋招提前批正式启动。</p>",
            images=[],
            content_hash="demo_cloudraccoon_2027",
        )
        upsert_article(conn, demo, source="seed_demo", source_query="demo", max_age_days=3650)
    conn.commit()


def upsert_article(conn: Any, parsed: ParsedArticle, source: str, source_query: str = "", max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> int:
    source_level = grade_article(conn, parsed, source)
    q_score, blocked, reason = quality_score(parsed, source_level)
    f_score, stale = freshness_score(parsed.publish_at, max_age_days)
    account_policy = lookup_account(conn, parsed.account_name, parsed.account_biz)
    if int(account_policy.get("is_blocked") or 0):
        blocked = True
        reason = reason + ",blocked_account"
    ts = utc_now()
    conn.execute(
        """
        INSERT INTO wechat_articles(canonical_url, original_url, title, account_name, account_biz, digest, cover_url, publish_at,
            content_text, content_html, source, source_query, source_level, quality_score, freshness_score, is_stale,
            is_blocked_source, block_reason, content_hash, parser_version, first_seen_at, last_seen_at, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(canonical_url) DO UPDATE SET
            original_url=excluded.original_url,
            title=excluded.title,
            account_name=excluded.account_name,
            account_biz=excluded.account_biz,
            digest=excluded.digest,
            cover_url=excluded.cover_url,
            publish_at=COALESCE(excluded.publish_at, wechat_articles.publish_at),
            content_text=excluded.content_text,
            content_html=excluded.content_html,
            source=excluded.source,
            source_query=excluded.source_query,
            source_level=excluded.source_level,
            quality_score=excluded.quality_score,
            freshness_score=excluded.freshness_score,
            is_stale=excluded.is_stale,
            is_blocked_source=excluded.is_blocked_source,
            block_reason=excluded.block_reason,
            content_hash=excluded.content_hash,
            parser_version=excluded.parser_version,
            last_seen_at=excluded.last_seen_at,
            fetched_at=excluded.fetched_at
        """,
        (
            parsed.canonical_url,
            parsed.original_url,
            parsed.title,
            parsed.account_name,
            parsed.account_biz,
            parsed.digest,
            parsed.cover_url,
            parsed.publish_at,
            parsed.content_text,
            parsed.content_html,
            source,
            source_query,
            source_level,
            q_score,
            f_score,
            int(stale),
            int(blocked),
            reason,
            parsed.content_hash,
            PARSER_VERSION,
            ts,
            ts,
            ts,
        ),
    )
    article_id = int(conn.execute("SELECT id FROM wechat_articles WHERE canonical_url=?", (parsed.canonical_url,)).fetchone()[0])
    conn.execute("DELETE FROM wechat_article_images WHERE article_id=?", (article_id,))
    for index, image_url in enumerate(parsed.images or []):
        conn.execute(
            "INSERT OR IGNORE INTO wechat_article_images(article_id, image_url, image_order, created_at) VALUES (?, ?, ?, ?)",
            (article_id, image_url, index, ts),
        )
    conn.commit()
    return article_id


def ingest_html(original_url: str, html_text: str, source: str = "manual_html", source_query: str = "", max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> dict[str, Any]:
    if not is_wechat_article_url(original_url):
        raise ValueError("url must be a public mp.weixin.qq.com article URL")
    parsed = parse_wechat_article_html(html_text, original_url)
    with get_connection() as conn:
        ensure_wechat_seed_data(conn)
        article_id = upsert_article(conn, parsed, source=source, source_query=source_query, max_age_days=max_age_days)
        return get_article(conn, article_id) or {}


def fetch_public_article(url: str, timeout: int = 10) -> str:
    if os.getenv("ENABLE_WECHAT_PUBLIC_FETCH", "0") != "1":
        raise RuntimeError("public WeChat article fetch is disabled. Set ENABLE_WECHAT_PUBLIC_FETCH=1 after reviewing rate limits and policy.")
    if not is_wechat_article_url(url):
        raise ValueError("only public mp.weixin.qq.com article URLs are allowed")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def ingest_url(url: str, source: str = "wechat_public_article", source_query: str = "", max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> dict[str, Any]:
    html_text = fetch_public_article(url)
    return ingest_html(url, html_text, source=source, source_query=source_query, max_age_days=max_age_days)


def get_article(conn: Any, article_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM wechat_articles WHERE id=?", (article_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    images = conn.execute("SELECT image_url, image_order FROM wechat_article_images WHERE article_id=? ORDER BY image_order", (article_id,)).fetchall()
    item["images"] = [dict(r) for r in images]
    item["age_days"] = days_since(item.get("publish_at"))
    return item


def search_articles(q: str = "", freshness_days: int | None = DEFAULT_MAX_AGE_DAYS, trusted_only: bool = False, include_stale: bool = False, min_source_level: str = "", limit: int = 50) -> dict[str, Any]:
    clauses = ["is_blocked_source = 0"]
    params: list[Any] = []
    for token in [x for x in re.split(r"\s+", (q or "").strip()) if x]:
        like = f"%{token}%"
        clauses.append("(title LIKE ? OR account_name LIKE ? OR digest LIKE ? OR content_text LIKE ?)")
        params.extend([like, like, like, like])
    if trusted_only:
        clauses.append("source_level IN ('S','A')")
    if min_source_level:
        allowed = [grade for grade, rank in SOURCE_RANK.items() if rank >= SOURCE_RANK.get(min_source_level, 0)]
        clauses.append("source_level IN (" + ",".join("?" for _ in allowed) + ")")
        params.extend(allowed)
    if not include_stale:
        clauses.append("is_stale = 0")
    if not include_stale and freshness_days is not None and freshness_days > 0:
        # Known old articles are excluded by default. Missing publish_at remains searchable but ranks lower.
        clauses.append("(publish_at IS NULL OR datetime(publish_at) >= datetime('now', ?))")
        params.append(f"-{freshness_days} days")
    where = " WHERE " + " AND ".join(clauses)
    with get_connection() as conn:
        ensure_wechat_seed_data(conn)
        rows = conn.execute(
            f"""
            SELECT *,
              (quality_score * 3.0 + freshness_score * 2.0 +
               CASE source_level WHEN 'S' THEN 2.0 WHEN 'A' THEN 1.4 WHEN 'B' THEN 0.8 WHEN 'C' THEN 0.2 ELSE 0 END +
               CASE WHEN title LIKE ? THEN 1.2 ELSE 0 END) AS rank_score
            FROM wechat_articles
            {where}
            ORDER BY rank_score DESC, publish_at DESC, last_seen_at DESC
            LIMIT ?
            """,
            (f"%{q}%", *params, limit),
        ).fetchall()
        items = [dict(row) for row in rows]
    for item in items:
        item["age_days"] = days_since(item.get("publish_at"))
    return {"items": items, "count": len(items), "query": q}


class SogouResultParser(HTMLParser):
    def __init__(self, source_query: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.source_query = source_query
        self.results: list[ArticleCandidate] = []
        self.in_item = False
        self.current: dict[str, Any] = {}
        self.tag_stack: list[str] = []
        self.text_parts: list[str] = []
        self.current_link = ""
        self.current_image = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        if tag == "li" and (attr.get("id", "").startswith("sogou_vr_") or "news-list" in attr.get("class", "")):
            self.in_item = True
            self.current = {}
            self.text_parts = []
            self.current_link = ""
            self.current_image = ""
        if not self.in_item:
            return
        self.tag_stack.append(tag)
        href = attr.get("href") or ""
        if tag == "a" and href and not self.current_link:
            self.current_link = urllib.parse.urljoin("https://weixin.sogou.com", href)
        if tag == "img" and not self.current_image:
            self.current_image = attr.get("src") or attr.get("data-src") or ""
            if self.current_image.startswith("//"):
                self.current_image = "https:" + self.current_image
        for key in ["t", "data-time", "time"]:
            if attr.get(key):
                self.current["publish_at"] = parse_datetime(attr[key])

    def handle_endtag(self, tag: str) -> None:
        if self.in_item and tag == "li":
            text = normalize_space(" ".join(self.text_parts))
            url = normalize_wechat_url(self.current.get("url") or self.current_link)
            title = self.current.get("title") or text[:80]
            digest = self.current.get("digest") or text[:240]
            self.results.append(ArticleCandidate(url=url, title=title, digest=digest, cover_url=self.current_image, publish_at=self.current.get("publish_at"), provider="sogou_weixin_search", source_query=self.source_query))
            self.in_item = False
            self.current = {}
            self.text_parts = []
            self.current_link = ""
            self.current_image = ""
        if self.in_item and self.tag_stack:
            self.tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if not self.in_item:
            return
        value = normalize_space(data)
        if not value:
            return
        self.text_parts.append(value)
        if not self.current.get("title") and "h3" in self.tag_stack:
            self.current["title"] = value


def parse_sogou_results(html_text: str, source_query: str = "") -> list[ArticleCandidate]:
    if "antispider" in html_text or ("验证码" in html_text and "weixin.sogou.com" in html_text):
        raise RuntimeError("Sogou returned an anti-spider or verification page. Stop and retry later; do not bypass captcha.")
    parser = SogouResultParser(source_query=source_query)
    parser.feed(html_text or "")
    results = [c for c in parser.results if c.url]
    if not results:
        seen: set[str] = set()
        for match in WECHAT_URL_RE.finditer(html_text or ""):
            url = normalize_wechat_url(match.group(0))
            if url not in seen:
                seen.add(url)
                results.append(ArticleCandidate(url=url, provider="sogou_weixin_search", source_query=source_query))
    return results


def build_sogou_search_url(keyword: str, page: int = 1, freshness_days: int = DEFAULT_MAX_AGE_DAYS) -> str:
    params: dict[str, Any] = {"type": 2, "query": keyword, "page": page, "ie": "utf8"}
    if freshness_days <= 1:
        params["tsn"] = 1
    elif freshness_days <= 7:
        params["tsn"] = 2
    elif freshness_days <= 30:
        params["tsn"] = 3
    return "https://weixin.sogou.com/weixin?" + urllib.parse.urlencode(params)


def build_browser_search_urls(keyword: str, freshness_days: int = DEFAULT_MAX_AGE_DAYS) -> dict[str, str]:
    query = f"site:{MP_HOST}/s {keyword}".strip()
    google_params: dict[str, Any] = {"q": query}
    if freshness_days > 0:
        end = datetime.now()
        start = end - timedelta(days=freshness_days)
        google_params["tbs"] = f"cdr:1,cd_min:{start:%m/%d/%Y},cd_max:{end:%m/%d/%Y}"
    return {
        "google": "https://www.google.com/search?" + urllib.parse.urlencode(google_params),
        "bing": "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query}),
        "sogou": build_sogou_search_url(keyword, freshness_days=freshness_days),
    }


def _coerce_candidate(candidate: ArticleCandidate | dict[str, Any], provider: str, keyword: str) -> ArticleCandidate:
    if isinstance(candidate, ArticleCandidate):
        return candidate
    return ArticleCandidate(
        url=str(candidate.get("url") or ""),
        title=str(candidate.get("title") or ""),
        account_name=str(candidate.get("account_name") or ""),
        digest=str(candidate.get("digest") or ""),
        cover_url=str(candidate.get("cover_url") or ""),
        publish_at=candidate.get("publish_at"),
        provider=str(candidate.get("provider") or provider),
        source_query=str(candidate.get("source_query") or keyword),
        score=float(candidate.get("score") or 0.0),
        raw=candidate.get("raw") if isinstance(candidate.get("raw"), dict) else None,
    )


def _save_discovery_candidates(
    conn: Any,
    run_id: int,
    provider: str,
    keyword: str,
    candidates: Iterable[ArticleCandidate | dict[str, Any]],
    freshness_days: int,
    ts: str,
) -> tuple[list[dict[str, Any]], int]:
    stale = 0
    saved: list[dict[str, Any]] = []
    for raw_candidate in candidates:
        candidate = _coerce_candidate(raw_candidate, provider=provider, keyword=keyword)
        canonical = normalize_wechat_url(candidate.url)
        age = days_since(candidate.publish_at)
        status = "found"
        reason = ""
        if not is_wechat_article_url(canonical):
            status = "rejected"
            reason = "not_wechat_article_url"
        elif age is not None and freshness_days > 0 and age > freshness_days:
            status = "stale"
            reason = f"older_than_{freshness_days}_days"
            stale += 1
        conn.execute(
            """INSERT OR IGNORE INTO wechat_discovery_candidates(run_id, provider, query, candidate_url, canonical_url, title, account_name, digest, cover_url, publish_at, status, reject_reason, score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, provider, keyword, candidate.url, canonical, candidate.title, candidate.account_name, candidate.digest, candidate.cover_url, candidate.publish_at, status, reason, candidate.score, ts),
        )
        saved.append({**asdict(candidate), "canonical_url": canonical, "status": status, "reject_reason": reason})
    return saved, stale


def discover_sogou(keyword: str, page: int = 1, freshness_days: int = DEFAULT_MAX_AGE_DAYS, html_text: str | None = None) -> dict[str, Any]:
    ts = utc_now()
    with get_connection() as conn:
        ensure_wechat_seed_data(conn)
        cur = conn.execute(
            "INSERT INTO wechat_discovery_runs(query, provider, freshness_days, status, started_at) VALUES (?, ?, ?, ?, ?)",
            (keyword, "sogou_weixin_search", freshness_days, "running", ts),
        )
        run_id = int(cur.lastrowid)
        try:
            if html_text is None:
                if os.getenv("ENABLE_SOGOU_DISCOVERY", "0") != "1":
                    raise RuntimeError("Sogou discovery is disabled. Set ENABLE_SOGOU_DISCOVERY=1 after reviewing limits and policy.")
                time.sleep(float(os.getenv("SOGOU_REQUEST_DELAY_SECONDS", "2.0")))
                url = build_sogou_search_url(keyword, page=page, freshness_days=freshness_days)
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    html_text = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
            candidates = parse_sogou_results(html_text or "", source_query=keyword)
            saved, stale = _save_discovery_candidates(conn, run_id, "sogou_weixin_search", keyword, candidates, freshness_days, ts)
            conn.execute(
                "UPDATE wechat_discovery_runs SET status=?, results_found=?, stale_rejected=?, finished_at=?, details_json=? WHERE id=?",
                ("finished", len(saved), stale, utc_now(), json.dumps({"page": page}, ensure_ascii=False), run_id),
            )
            conn.commit()
            return {"run_id": run_id, "items": saved, "count": len(saved), "stale_rejected": stale}
        except Exception as exc:
            conn.execute("UPDATE wechat_discovery_runs SET status=?, error=?, finished_at=? WHERE id=?", ("failed", str(exc), utc_now(), run_id))
            conn.commit()
            raise


def list_discovery_runs(limit: int = 30) -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM wechat_discovery_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return {"items": [dict(r) for r in rows], "count": len(rows)}


def list_sources() -> dict[str, Any]:
    with get_connection() as conn:
        ensure_wechat_seed_data(conn)
        rows = conn.execute(
            """
            SELECT * FROM wechat_article_sources
            WHERE source_type NOT IN ('google_cse', 'bing_web_search', 'firecrawl_search', 'tavily_search')
            ORDER BY trust_level DESC, name ASC
            """
        ).fetchall()
    return {"items": [dict(r) for r in rows], "count": len(rows)}


def get_article_by_id(article_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        ensure_wechat_seed_data(conn)
        return get_article(conn, article_id)
