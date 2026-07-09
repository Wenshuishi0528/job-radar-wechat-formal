from __future__ import annotations

import html
import json
import os
import re
import ssl
import time
import base64
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from .database import get_connection
from .extraction import CITY_KEYWORDS, infer_job_family
from .repository import get_job, import_discovered_campaign, import_scraped_job
from .source_registry import source_for_text, source_for_url, sources_for_keyword
from .wechat_articles import (
    MP_HOST,
    WECHAT_URL_RE,
    build_sogou_search_url,
    ensure_wechat_seed_data,
    ingest_url,
    normalize_wechat_url,
    parse_sogou_results,
    utc_now,
)


SEARCH_PROVIDERS = {"google", "bing", "sogou", "both", "all"}
SOURCE_SCOPES = {"all", "official", "job_boards", "open_web", "university", "wechat"}
SEARCH_ENGINE_HOSTS = {
    "google.com", "www.google.com", "bing.com", "www.bing.com", "weixin.sogou.com", "sogou.com", "www.sogou.com",
}
CHNENERGY_RECRUIT_HOST = "zhaopin.chnenergy.com.cn"
STATIC_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js", ".ico", ".zip")
RECRUITING_TERMS = "(校园招聘 OR 校招 OR 秋招 OR 春招 OR 暑期实习 OR 实习 OR 应届 OR 内推 OR 宣讲会)"
OFFICIAL_RECRUITING_DOMAINS = [
    "site:zhaopin.chnenergy.com.cn",
    "site:zhaopin.sgcc.com.cn",
    "site:zhaopin.csg.cn",
    "site:zhaopin.china-cdt.com",
    "site:ceec.iguopin.com",
    "site:zhaopin.powerchina.cn",
    "site:jobs.bytedance.com",
    "site:careers.tencent.com",
    "site:join.qq.com",
    "site:campus.alibaba.com",
    "site:career.huawei.com",
    "site:talent.baidu.com",
    "site:campus.jd.com",
    "site:zhaopin.meituan.com",
    "site:careers.pinduoduo.com",
    "site:careers.mi.com",
    "site:hr.xiaomi.com",
    "site:careers.oppo.com",
    "site:hr.vivo.com",
    "site:career.lenovo.com",
    "site:career.cmbchina.com",
    "site:hotjob.cn",
]
CURATED_OFFICIAL_SOURCES = [
    {
        "name": "国家能源集团",
        "aliases": ["国家能源集团", "国家能源投资集团", "中国能源集团", "国能集团", "chnenergy"],
        "industry": "能源央企",
        "urls": [
            ("国家能源集团人力资源招聘系统", "https://zhaopin.chnenergy.com.cn/"),
            ("国家能源集团校园招聘岗位入口", "https://zhaopin.chnenergy.com.cn/recTypeSerch?kinds=1"),
            ("国家能源集团招聘公告列表", "https://zhaopin.chnenergy.com.cn/annc/annclist?ggtype=1"),
        ],
    },
    {
        "name": "中国能源建设集团",
        "aliases": ["中国能建", "中国能源建设集团", "中国能源建设股份", "ceec"],
        "industry": "能源建设央企",
        "urls": [
            ("中国能建校园招聘入口", "https://ceec.iguopin.com/"),
            ("中国能建校招岗位列表", "https://ceec.iguopin.com/job"),
            ("中国能建诚聘英才", "https://www.ceec.net.cn/col/col11057/index.html"),
        ],
    },
    {
        "name": "国家电网",
        "aliases": ["国家电网", "国家电网公司", "sgcc"],
        "industry": "电网央企",
        "urls": [("国家电网招聘平台", "https://zhaopin.sgcc.com.cn/")],
    },
    {
        "name": "中国南方电网",
        "aliases": ["南方电网", "中国南方电网", "csg"],
        "industry": "电网央企",
        "urls": [("中国南方电网招聘系统", "https://zhaopin.csg.cn/")],
    },
    {
        "name": "中国大唐集团",
        "aliases": ["中国大唐", "中国大唐集团", "大唐集团", "china-cdt"],
        "industry": "电力央企",
        "urls": [("中国大唐集团招聘系统", "https://zhaopin.china-cdt.com/")],
    },
    {
        "name": "中国电建",
        "aliases": ["中国电建", "中国电力建设集团", "powerchina"],
        "industry": "能源建设央企",
        "urls": [("中国电建招聘平台", "https://zhaopin.powerchina.cn/")],
    },
]
ANTI_AUTOMATION_MARKERS = [
    "our systems have detected unusual traffic",
    "detected unusual traffic",
    "/sorry/",
    "before you continue to google",
    "consent.google",
    "unusual activity",
    "verify you are a human",
    "captcha",
    "验证码",
]
RECRUITMENT_TITLE_TERMS = (
    "校园招聘", "校招", "秋招", "春招", "提前批", "招聘公告", "招聘启动", "招聘正式启动",
    "实习生招聘", "暑期实习", "高校毕业生招聘", "应届生招聘", "管培生招聘", "人才招聘",
)
RECRUITMENT_PATH_TERMS = ("zhaopin", "career", "careers", "campus", "job", "recruit", "hotjob", "talent")
REJECTED_ANNOUNCEMENT_TERMS = (
    "白皮书", "避坑指南", "招聘会", "双选会", "宣讲会", "就业启动大会", "圆满收官", "趋势", "如何", "面试技巧", "笔试真题",
    "成绩查询", "录用名单", "拟录用", "考试通知", "笔试通知", "求职困境", "规则形同虚设", "应届生说", "内定",
)


class WebSearchImportError(RuntimeError):
    pass


@dataclass
class WebSearchCandidate:
    url: str
    canonical_url: str
    title: str = ""
    snippet: str = ""
    provider: str = "unknown"
    source_query: str = ""
    source_scope: str = "all"
    candidate_type: str = "web_signal"
    status: str = "found"
    reject_reason: str = ""
    imported: bool = False
    article_id: int | None = None
    signal_id: int | None = None
    campaign_id: int | None = None
    job_ids: list[int] | None = None
    company_name: str = ""
    publisher: str = ""
    publisher_url: str = ""
    published_at: str | None = None
    error: str = ""


def _is_web_search_enabled() -> bool:
    return os.getenv("ENABLE_WEB_SEARCH_IMPORT", "0") == "1" or os.getenv("JOB_RADAR_PERSONAL_MODE", "0") == "1"


def _https_context() -> ssl.SSLContext | None:
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def _open_url(request: urllib.request.Request, timeout: int = 15) -> Any:
    return urllib.request.urlopen(request, timeout=timeout, context=_https_context())


def _provider_list(provider: str) -> list[str]:
    if provider not in SEARCH_PROVIDERS:
        raise ValueError("provider must be google, bing, sogou, both, or all")
    if provider == "all":
        return ["google", "bing", "sogou"]
    return ["google", "bing"] if provider == "both" else [provider]


def _normalize_source_scope(source_scope: str) -> str:
    if source_scope not in SOURCE_SCOPES:
        raise ValueError("source_scope must be all, official, job_boards, open_web, university, or wechat")
    return source_scope


def _compact_keyword(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").lower())


def fetch_curated_official_results(keyword: str, source_scope: str = "all", max_results: int = 10) -> list[WebSearchCandidate]:
    if source_scope not in {"all", "official"}:
        return []
    candidates: list[WebSearchCandidate] = []
    seen: set[str] = set()
    for source in sources_for_keyword(keyword, limit=max_results):
        item = _candidate_from_url(
            source.url,
            "official_catalog",
            keyword,
            title=source.title,
            snippet=f"{source.name}（{source.industry}）官方招聘入口。",
            source_scope="official",
        )
        if item and item.canonical_url not in seen:
            item.company_name = source.name
            item.publisher = source.name
            item.publisher_url = source.url
            seen.add(item.canonical_url)
            candidates.append(item)
            if len(candidates) >= max_results:
                return candidates
    return candidates


def _official_source_name_for_url(url: str) -> str:
    registry_source = source_for_url(url)
    if registry_source:
        return registry_source.name
    normalized = _normalize_web_url(url)
    for source in CURATED_OFFICIAL_SOURCES:
        for _, source_url in source["urls"]:
            if normalized == _normalize_web_url(source_url) or urllib.parse.urlparse(normalized).netloc == urllib.parse.urlparse(source_url).netloc:
                return source["name"]
    return ""


def build_search_query(keyword: str, source_scope: str = "all") -> str:
    source_scope = _normalize_source_scope(source_scope)
    keyword = keyword.strip()
    if source_scope == "wechat":
        return f"site:{MP_HOST}/s {keyword}".strip()
    if source_scope == "official":
        domains = " OR ".join(OFFICIAL_RECRUITING_DOMAINS)
        return f"{keyword} {RECRUITING_TERMS} (官方招聘 OR 招聘官网 OR 人力资源招聘网站 OR 报名入口 OR 简历投递 OR careers OR campus OR {domains})".strip()
    if source_scope == "job_boards":
        domains = " OR ".join(["site:zhipin.com", "site:liepin.com", "site:51job.com", "site:lagou.com", "site:nowcoder.com/jobs"])
        return f"{keyword} {RECRUITING_TERMS} ({domains})".strip()
    if source_scope == "open_web":
        domains = " OR ".join(["site:github.com", "site:gitee.com", "site:nowcoder.com/discuss", "site:v2ex.com", "site:kanzhun.com"])
        return f"{keyword} (求职 OR 招聘 OR 内推 OR 校招 OR 实习 OR 面经) ({domains})".strip()
    if source_scope == "university":
        return f"{keyword} {RECRUITING_TERMS} (site:edu.cn OR site:job.cingta.com)".strip()
    return f"{keyword} {RECRUITING_TERMS} (官方招聘 OR 招聘官网 OR 招聘公告 OR 报名入口 OR 简历投递)".strip()


def build_plain_search_url(provider: str, keyword: str, freshness_days: int = 45, start: int = 0, source_scope: str = "all") -> str:
    query = build_search_query(keyword, source_scope=source_scope)
    if provider == "google":
        params: dict[str, Any] = {"q": query, "num": 10, "hl": "zh-CN"}
        if freshness_days > 0:
            end = datetime.now()
            begin = end - timedelta(days=freshness_days)
            params["tbs"] = f"cdr:1,cd_min:{begin:%m/%d/%Y},cd_max:{end:%m/%d/%Y}"
        if start:
            params["start"] = start
        return "https://www.google.com/search?" + urllib.parse.urlencode(params)
    if provider == "bing":
        params = {"q": query, "count": 10, "setlang": "zh-Hans"}
        if start:
            params["first"] = start + 1
        return "https://www.bing.com/search?" + urllib.parse.urlencode(params)
    raise ValueError("provider must be google or bing")


def _current_campus_year() -> int:
    now = datetime.now()
    return now.year + 1 if now.month >= 6 else now.year


def build_google_news_rss_url(keyword: str, freshness_days: int = 45) -> str:
    compact = _compact_keyword(keyword)
    query = keyword.strip()
    if "秋招" in compact and not re.search(r"20\d{2}", query):
        query = f'"{_current_campus_year()}届" (校园招聘 OR 秋招 OR 提前批)'
    elif "春招" in compact and not re.search(r"20\d{2}", query):
        query = f'"{datetime.now().year}届" (春季校园招聘 OR 春招)'
    elif not any(term in compact for term in ["招聘", "校招", "秋招", "春招", "实习", "提前批"]):
        query = f"{query} 校园招聘"
    if freshness_days > 0:
        query = f"{query} when:{freshness_days}d"
    params = {"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)


def _google_news_query_variants(keyword: str) -> list[str]:
    compact = _compact_keyword(keyword)
    if "秋招" in compact and not re.search(r"20\d{2}", keyword):
        year = _current_campus_year()
        return [
            f'"{year}届" 校园招聘',
            f'"{year}届" 秋招',
            f'"{year}届" 提前批',
            f'"{year}届" 校招启动',
        ]
    return [keyword]


def _strip_news_publisher(title: str, publisher: str) -> str:
    value = _text_from_html(title)
    suffix = f" - {publisher}" if publisher else ""
    if suffix and value.endswith(suffix):
        value = value[:-len(suffix)]
    if publisher:
        value = re.sub(rf"(?:_|\||｜|-)\s*{re.escape(publisher)}$", "", value).strip()
    if "_手机新浪网" in value or value.endswith("_新浪新闻"):
        value = value.split("|", 1)[0]
        value = re.sub(r"_(?:手机)?新浪(?:网|新闻)$", "", value)
    return value.strip()


def parse_google_news_results(xml_text: str, keyword: str, source_scope: str = "all", max_results: int = 20) -> list[WebSearchCandidate]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise WebSearchImportError(f"Google News returned invalid RSS: {exc}") from exc
    items: list[WebSearchCandidate] = []
    for node in root.findall("./channel/item"):
        source_node = node.find("source")
        publisher = (source_node.text or "").strip() if source_node is not None else ""
        publisher_url = (source_node.attrib.get("url") or "").strip() if source_node is not None else ""
        title = _strip_news_publisher(node.findtext("title") or "", publisher)
        link = (node.findtext("link") or "").strip()
        description = _text_from_html(node.findtext("description") or "")
        published_at = None
        raw_date = node.findtext("pubDate")
        if raw_date:
            try:
                published_at = parsedate_to_datetime(raw_date).astimezone().replace(microsecond=0).isoformat()
            except (TypeError, ValueError, OverflowError):
                published_at = None
        if not link or not title:
            continue
        source = source_for_text(title)
        items.append(WebSearchCandidate(
            url=link,
            canonical_url=link,
            title=title,
            snippet=description,
            provider="google",
            source_query=keyword,
            source_scope=source_scope,
            candidate_type="news_announcement",
            company_name=source.name if source else "",
            publisher=publisher,
            publisher_url=publisher_url,
            published_at=published_at,
        ))
        if len(items) >= max_results:
            break
    return items


def fetch_google_news_results(keyword: str, freshness_days: int = 45, max_results: int = 20, source_scope: str = "all") -> list[WebSearchCandidate]:
    if source_scope == "wechat":
        return []
    collected: list[WebSearchCandidate] = []
    seen: set[str] = set()
    for query in _google_news_query_variants(keyword):
        url = build_google_news_rss_url(query, freshness_days=freshness_days)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": os.getenv("JOB_RADAR_BROWSER_USER_AGENT", "Mozilla/5.0 JobRadar personal local news search"),
                "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.5",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            },
        )
        with _open_url(request, timeout=15) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
        parsed = parse_google_news_results(body, keyword=keyword, source_scope=source_scope, max_results=100)
        for item in parsed:
            title_key = re.sub(r"\W+", "", item.title.lower())
            if title_key in seen or not _is_relevant_candidate(item):
                continue
            seen.add(title_key)
            collected.append(item)
    collected.sort(
        key=lambda item: (
            1 if source_for_text(item.title) else 0,
            1 if urllib.parse.urlparse(item.publisher_url).netloc.endswith(".gov.cn") else 0,
            item.published_at or "",
        ),
        reverse=True,
    )
    return collected[:max_results]


def _decode_repeatedly(value: str, rounds: int = 3) -> str:
    decoded = html.unescape(value or "")
    for _ in range(rounds):
        next_value = urllib.parse.unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def _concrete_wechat_url(url: str) -> str:
    canonical = normalize_wechat_url(url)
    parsed = urllib.parse.urlparse(canonical)
    if parsed.netloc != MP_HOST:
        return ""
    if parsed.path.startswith("/s/") and len(parsed.path) > len("/s/"):
        return canonical
    if parsed.path == "/s":
        qs = urllib.parse.parse_qs(parsed.query)
        required = {"__biz", "mid", "idx", "sn"}
        if required.issubset(qs):
            return canonical
    return ""


def _normalize_web_url(url: str) -> str:
    url = _decode_repeatedly(url).strip()
    if url.startswith("//"):
        url = "https:" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    parsed = parsed._replace(fragment="")
    tracking_keys = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "spm", "from", "fr"}
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if k not in tracking_keys]
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", urllib.parse.urlencode(query), ""))


def _is_ignored_result_url(url: str) -> bool:
    normalized = _normalize_web_url(url)
    if not normalized:
        return True
    parsed = urllib.parse.urlparse(normalized)
    host = parsed.netloc.lower().removeprefix("www.")
    if host in {h.removeprefix("www.") for h in SEARCH_ENGINE_HOSTS}:
        return True
    if host.endswith(".google.com") or host.endswith(".bing.com") or host.endswith(".sogou.com"):
        return True
    if parsed.path.lower().endswith(STATIC_EXTENSIONS):
        return True
    if any(part in normalized.lower() for part in ["googleusercontent.com", "bingj.com", "mmbiz.qpic.cn"]):
        return True
    return False


def _candidate_from_url(url: str, provider: str, keyword: str, title: str = "", snippet: str = "", source_scope: str = "all") -> WebSearchCandidate | None:
    canonical = _concrete_wechat_url(url)
    candidate_type = "wechat_article"
    if not canonical:
        canonical = _normalize_web_url(url)
        candidate_type = "web_signal"
    if not canonical or _is_ignored_result_url(canonical):
        return None
    if source_scope == "wechat" and candidate_type != "wechat_article":
        return None
    return WebSearchCandidate(
        url=url,
        canonical_url=canonical,
        title=title,
        snippet=snippet,
        provider=provider,
        source_query=keyword,
        source_scope=source_scope,
        candidate_type=candidate_type,
    )


def _extract_wechat_urls(text: str) -> list[str]:
    decoded = _decode_repeatedly(text)
    urls: list[str] = []
    seen: set[str] = set()
    for match in WECHAT_URL_RE.finditer(decoded):
        canonical = _concrete_wechat_url(match.group(0))
        if canonical and canonical not in seen:
            seen.add(canonical)
            urls.append(canonical)
    return urls


def _extract_redirect_targets(text: str) -> list[str]:
    decoded = _decode_repeatedly(text)
    targets: list[str] = []
    for raw_url in re.findall(r"https?://(?:www\.)?google\.com/url\?[^\"'<> ]+|/url\?[^\"'<> ]+", decoded, flags=re.I):
        parsed = urllib.parse.urlparse(urllib.parse.urljoin("https://www.google.com", raw_url))
        qs = urllib.parse.parse_qs(parsed.query)
        for key in ["q", "url"]:
            if qs.get(key):
                targets.append(qs[key][0])
    for raw_url in re.findall(r"https?://www\.bing\.com/ck/a\?[^\"'<> ]+", decoded, flags=re.I):
        parsed = urllib.parse.urlparse(raw_url)
        qs = urllib.parse.parse_qs(parsed.query)
        for key in ["u", "r"]:
            if qs.get(key):
                value = qs[key][0]
                if value.startswith("a1"):
                    value = value[2:]
                    try:
                        padding = "=" * (-len(value) % 4)
                        value = base64.urlsafe_b64decode((value + padding).encode("utf-8")).decode("utf-8", errors="replace")
                    except Exception:
                        pass
                try:
                    value = _decode_repeatedly(value)
                except Exception:
                    pass
                targets.append(value)
    return targets


def _text_from_html(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", value or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _html_to_lines(value: str) -> list[str]:
    text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", value or "", flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|li|h\d|td|tr|ul|ol|section|article)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [re.sub(r"\s+", " ", html.unescape(line)).strip() for line in text.splitlines()]
    return [line for line in lines if line and line not in {"|", "-->"}]


def _extract_links(html_text: str, base_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_text or "", flags=re.I | re.S):
        href = html.unescape(match.group(1))
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        links.append((urllib.parse.urljoin(base_url, href), _text_from_html(match.group(2))))
    return links


def _extract_href_candidates(provider: str, html_text: str) -> list[tuple[str, str]]:
    base_url = "https://www.google.com" if provider == "google" else "https://www.bing.com"
    return _extract_links(html_text, base_url)


def _degree_from_text(value: str) -> str:
    compact = _compact_keyword(value)
    if "博士" in compact:
        return "phd"
    if "硕士" in compact or "研究生" in compact:
        return "master"
    if "本科" in compact:
        return "bachelor"
    if "专科" in compact or "大专" in compact:
        return "associate"
    return "bachelor"


def _cities_from_text(value: str) -> list[str]:
    found: list[str] = []
    for city in CITY_KEYWORDS:
        if city in value and city not in found:
            found.append(city)
    compact = value.replace(" ", "")
    if not found:
        for city in ["内蒙古包头", "黑龙江双鸭山", "陕西榆林"]:
            if city in compact:
                found.append(city)
    return found


def _is_job_title_candidate(value: str) -> bool:
    if not value or len(value) > 40:
        return False
    banned = ["搜索", "申请", "报名截止", "招聘人数", "全部", "学历要求", "发布时间", "岗位地点", "工作单位", "招聘岗位", "岗位类型"]
    if any(word in value for word in banned):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", value))


def _extract_attr(value: str, attr: str) -> str:
    match = re.search(rf'\b{re.escape(attr)}=["\']([^"\']+)["\']', value or "", flags=re.I)
    return html.unescape(match.group(1)).strip() if match else ""


def _extract_chnenergy_station_jobs(html_text: str, source_url: str, default_company: str, source_level: str, max_jobs: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for block_match in re.finditer(r'<li\b[^>]*class=["\'][^"\']*list-group-item[^"\']*["\'][^>]*>(.*?)</li>', html_text or "", flags=re.I | re.S):
        block = block_match.group(1)
        link_match = re.search(r'<a\b([^>]*)href=["\']([^"\']*?/annc/showgw\?id=[^"\']+)["\']([^>]*)>(.*?)</a>', block, flags=re.I | re.S)
        if not link_match:
            continue
        attrs = f"{link_match.group(1)} {link_match.group(3)}"
        title = _extract_attr(attrs, "title") or _text_from_html(link_match.group(4))
        if not _is_job_title_candidate(title):
            continue
        span_titles = re.findall(r'<span\b[^>]*title=["\']([^"\']+)["\'][^>]*>', block, flags=re.I | re.S)
        span_titles = [html.unescape(item).strip() for item in span_titles if html.unescape(item).strip()]
        if len(span_titles) < 2:
            continue
        company_name = span_titles[0]
        majors_text = span_titles[1] if len(span_titles) > 1 else ""
        text = _text_from_html(block)
        parts = [part.strip(" \u00a0") for part in re.split(r"\s*\|\s*", text) if part.strip(" \u00a0")]
        degree_text = ""
        city_text = ""
        for idx, part in enumerate(parts):
            if any(token in part for token in ["博士", "硕士", "研究生", "本科", "专科", "大专"]):
                degree_text = part
                if idx + 1 < len(parts):
                    city_text = parts[idx + 1]
                break
        if not majors_text:
            for part in parts:
                if "专业" in part or "工程" in part or "计算机" in part:
                    majors_text = part
                    break
        job_url = urllib.parse.urljoin(source_url, html.unescape(link_match.group(2)))
        key = (company_name, title)
        if key in seen:
            continue
        seen.add(key)
        block_text = " / ".join([part for part in [title, company_name, majors_text, degree_text, city_text] if part])
        jobs.append({
            "company_name": company_name or default_company,
            "company_aliases": [default_company] if default_company and default_company != company_name else [],
            "industry": "能源央企" if "能源" in default_company or "国能" in company_name else "unknown",
            "title": title,
            "campaign_name": f"{default_company} 校园招聘" if default_company != "未知公司" else "自动搜索校园招聘",
            "recruitment_type": "校招",
            "deadline": None,
            "degree_min": _degree_from_text(degree_text),
            "cities": _cities_from_text(city_text),
            "majors": [part for part in re.split(r"[,，、]", majors_text) if part],
            "job_family": infer_job_family(title, block_text),
            "description": block_text[:500],
            "source_url": source_url,
            "apply_url": job_url,
            "source_level": source_level,
            "quality_score": 0.82,
            "risk_level": "needs_review",
            "evidence_text": block_text[:600],
            "confidence": 0.8,
        })
        if len(jobs) >= max_jobs:
            break
    return jobs


def extract_jobs_from_html(html_text: str, source_url: str, default_company: str = "未知公司", source_level: str = "A", max_jobs: int = 20) -> list[dict[str, Any]]:
    station_jobs = _extract_chnenergy_station_jobs(html_text, source_url, default_company, source_level, max_jobs)
    if station_jobs:
        return station_jobs

    lines = _html_to_lines(html_text)
    jobs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for idx, line in enumerate(lines):
        if not line.startswith("招聘人数"):
            continue
        window = lines[max(0, idx - 10):idx]
        next_window = lines[idx + 1: idx + 8]
        degree_index = None
        for pos, item in enumerate(window):
            if any(token in item for token in ["博士", "硕士", "研究生", "本科", "专科", "大专"]):
                degree_index = pos
                break
        if degree_index is None or degree_index == 0:
            continue
        title = ""
        for candidate in reversed(window[:degree_index]):
            if _is_job_title_candidate(candidate):
                title = candidate
                break
        tail = window[degree_index + 1:]
        useful_tail = [item for item in tail if item not in {"|"} and not item.endswith("...")]
        if len(useful_tail) < 2:
            continue
        company_name = useful_tail[-2]
        city_text = useful_tail[-1]
        majors_text = "、".join(useful_tail[:-2])
        if not title or not _is_job_title_candidate(company_name):
            continue
        deadline = None
        for item in next_window:
            m = re.search(r"报名截止日期[:：]\s*(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", item)
            if m:
                deadline = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                break
        cities = _cities_from_text(city_text)
        key = (company_name, title, deadline or "")
        if key in seen:
            continue
        seen.add(key)
        deadline_text = f"报名截止日期：{deadline}" if deadline else ""
        block_parts = [title, window[degree_index], majors_text, company_name, city_text, line, deadline_text]
        block_text = " / ".join([part for part in block_parts if part])
        jobs.append({
            "company_name": company_name,
            "company_aliases": [default_company] if default_company and default_company != company_name else [],
            "industry": "能源央企" if "能源" in default_company or "国能" in company_name else "unknown",
            "title": title,
            "campaign_name": f"{default_company} 校园招聘" if default_company != "未知公司" else "自动搜索校园招聘",
            "recruitment_type": "校招",
            "deadline": deadline,
            "degree_min": _degree_from_text(window[degree_index]),
            "cities": cities,
            "majors": [part for part in re.split(r"[,，、]", majors_text) if part],
            "job_family": infer_job_family(title, block_text),
            "description": block_text[:500],
            "source_url": source_url,
            "apply_url": source_url,
            "source_level": source_level,
            "quality_score": 0.78,
            "risk_level": "needs_review",
            "evidence_text": block_text[:600],
            "confidence": 0.72,
        })
        if len(jobs) >= max_jobs:
            break
    return jobs


def _detect_blocked_search(provider: str, html_text: str, final_url: str = "") -> None:
    body = (html_text or "").lower()
    final = (final_url or "").lower()
    if any(marker in body or marker in final for marker in ANTI_AUTOMATION_MARKERS):
        raise WebSearchImportError(f"{provider} returned a verification or anti-automation page")


def parse_search_results(provider: str, html_text: str, keyword: str = "", source_scope: str = "all") -> list[WebSearchCandidate]:
    _detect_blocked_search(provider, html_text)
    candidates: list[WebSearchCandidate] = []
    seen: set[str] = set()
    for href, title in _extract_href_candidates(provider, html_text):
        targets = _extract_redirect_targets(href) or [href]
        for raw in targets:
            for url in _extract_wechat_urls(raw) or [raw]:
                candidate = _candidate_from_url(url, provider, keyword, title=title, source_scope=source_scope)
                if candidate and candidate.canonical_url not in seen:
                    seen.add(candidate.canonical_url)
                    candidates.append(candidate)
    raw_urls = [*_extract_redirect_targets(html_text), *_extract_wechat_urls(html_text)]
    for raw in raw_urls:
        for url in _extract_wechat_urls(raw) or [raw]:
            candidate = _candidate_from_url(url, provider, keyword, source_scope=source_scope)
            if candidate and candidate.canonical_url not in seen:
                seen.add(candidate.canonical_url)
                candidates.append(candidate)
    return candidates


def fetch_sogou_results(keyword: str, freshness_days: int = 45, max_results: int = 10, source_scope: str = "all") -> list[WebSearchCandidate]:
    if os.getenv("ENABLE_SOGOU_DISCOVERY", "0") != "1" and os.getenv("JOB_RADAR_PERSONAL_MODE", "0") != "1":
        raise WebSearchImportError("Sogou discovery is disabled. Start in personal mode or set ENABLE_SOGOU_DISCOVERY=1.")
    results: list[WebSearchCandidate] = []
    seen: set[str] = set()
    page = 1
    while len(results) < max_results and page <= 3:
        time.sleep(float(os.getenv("SOGOU_REQUEST_DELAY_SECONDS", "2.0")))
        url = build_sogou_search_url(keyword, page=page, freshness_days=freshness_days)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": os.getenv("JOB_RADAR_BROWSER_USER_AGENT", "Mozilla/5.0 JobRadar personal local search importer"),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with _open_url(request, timeout=15) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
        raw_candidates = parse_sogou_results(body, source_query=keyword)
        for raw in raw_candidates:
            age = None
            if raw.publish_at:
                try:
                    age = max(0, (datetime.now() - datetime.strptime(raw.publish_at[:19], "%Y-%m-%d %H:%M:%S")).days)
                except ValueError:
                    age = None
            item = _candidate_from_url(raw.url, "sogou", keyword, title=raw.title, snippet=raw.digest, source_scope="wechat" if source_scope == "wechat" else source_scope)
            if not item:
                continue
            if age is not None and freshness_days > 0 and age > freshness_days:
                item.status = "stale"
                item.reject_reason = f"older_than_{freshness_days}_days"
            if item.canonical_url not in seen:
                seen.add(item.canonical_url)
                results.append(item)
                if len(results) >= max_results:
                    break
        if not raw_candidates:
            break
        page += 1
    return results[:max_results]


def fetch_search_results(provider: str, keyword: str, freshness_days: int = 45, max_results: int = 10, source_scope: str = "all") -> list[WebSearchCandidate]:
    if not _is_web_search_enabled():
        raise WebSearchImportError("web search import is disabled. Start in personal mode or set ENABLE_WEB_SEARCH_IMPORT=1.")
    if provider == "sogou":
        if source_scope not in {"all", "wechat"}:
            return []
        return fetch_sogou_results(keyword, freshness_days=freshness_days, max_results=max_results, source_scope=source_scope)
    if provider == "google" and source_scope != "wechat":
        news_items = fetch_google_news_results(
            keyword,
            freshness_days=freshness_days,
            max_results=max_results,
            source_scope=source_scope,
        )
        if news_items:
            return news_items
    candidates: list[WebSearchCandidate] = []
    seen: set[str] = set()
    start = 0
    while len(candidates) < max_results and start < 30:
        url = build_plain_search_url(provider, keyword, freshness_days=freshness_days, start=start, source_scope=source_scope)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": os.getenv("JOB_RADAR_BROWSER_USER_AGENT", "Mozilla/5.0 JobRadar personal local search importer"),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with _open_url(request, timeout=15) as response:
            final_url = response.geturl()
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
        _detect_blocked_search(provider, body, final_url=final_url)
        page_candidates = parse_search_results(provider, body, keyword=keyword, source_scope=source_scope)
        for candidate in page_candidates:
            if candidate.canonical_url not in seen:
                seen.add(candidate.canonical_url)
                candidates.append(candidate)
                if len(candidates) >= max_results:
                    break
        if not page_candidates:
            break
        start += 10
        time.sleep(float(os.getenv("WEB_SEARCH_REQUEST_DELAY_SECONDS", "1.0")))
    return candidates[:max_results]


def _record_run(provider: str, keyword: str, freshness_days: int) -> int:
    ts = utc_now()
    with get_connection() as conn:
        ensure_wechat_seed_data(conn)
        cur = conn.execute(
            "INSERT INTO wechat_discovery_runs(query, provider, freshness_days, status, started_at) VALUES (?, ?, ?, ?, ?)",
            (keyword, f"{provider}_plain_search", freshness_days, "running", ts),
        )
        conn.commit()
        return int(cur.lastrowid)


def _record_candidate(run_id: int, candidate: WebSearchCandidate, freshness_days: int) -> None:
    ts = utc_now()
    age = None
    status = candidate.status
    reason = candidate.reject_reason
    if candidate.imported:
        status = "imported"
    elif candidate.error:
        status = "failed"
        reason = candidate.error
    elif age is not None and freshness_days > 0 and age > freshness_days:
        status = "stale"
        reason = f"older_than_{freshness_days}_days"
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO wechat_discovery_candidates(run_id, provider, query, candidate_url, canonical_url, title, account_name, digest, cover_url, publish_at, status, reject_reason, score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                f"{candidate.provider}_plain_search",
                candidate.source_query,
                candidate.url,
                candidate.canonical_url,
                candidate.title,
                "",
                "",
                "",
                None,
                status,
                reason,
                0.0,
                ts,
            ),
        )
        conn.commit()


def _finish_run(run_id: int, status: str, items: list[WebSearchCandidate], error: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE wechat_discovery_runs SET status=?, results_found=?, articles_ingested=?, error=?, finished_at=?, details_json=? WHERE id=?",
            (
                status,
                len(items),
                len([item for item in items if item.imported]),
                error,
                utc_now(),
                json.dumps({"plain_web_search": True}, ensure_ascii=False),
                run_id,
            ),
        )
        conn.commit()


def _create_signal_from_candidate(candidate: WebSearchCandidate) -> int:
    title = candidate.title.strip() or _signal_title_from_url(candidate.canonical_url)
    description = candidate.snippet.strip() or f"{candidate.provider} 搜索发现的招聘相关页面。"
    with get_connection() as conn:
        ensure_wechat_seed_data(conn)
        existing = conn.execute(
            "SELECT id FROM signals WHERE source_url=? AND signal_type='web_search_result' ORDER BY id DESC LIMIT 1",
            (candidate.canonical_url,),
        ).fetchone()
        if existing:
            signal_id = int(existing["id"])
            conn.execute(
                "UPDATE signals SET title=?, description=?, status=?, detected_at=?, evidence_text=? WHERE id=?",
                (title, description, "pending_review", utc_now(), f"{candidate.provider} / {candidate.source_scope} 搜索：{candidate.source_query}", signal_id),
            )
            conn.commit()
            return signal_id
        cur = conn.execute(
            """INSERT INTO signals(company_id, campaign_id, signal_type, title, description, source_url, source_level, status, detected_at, evidence_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                None,
                None,
                "web_search_result",
                title,
                description,
                candidate.canonical_url,
                _source_level_for_scope(candidate.source_scope, candidate.canonical_url),
                "pending_review",
                utc_now(),
                f"{candidate.provider} / {candidate.source_scope} 搜索：{candidate.source_query}",
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def _signal_title_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = parsed.path.strip("/").replace("-", " ").replace("_", " ")
    return f"{host} {path[:60]}".strip() or "招聘搜索线索"


def _source_level_for_scope(source_scope: str, url: str) -> str:
    registry_source = source_for_url(url)
    if registry_source:
        return registry_source.trust_level
    host = urllib.parse.urlparse(url).netloc.lower()
    if source_scope == "official" or any(token in host for token in ["career", "campus", "jobs", "talent"]):
        return "A"
    if source_scope in {"university", "wechat"}:
        return "B"
    return "C"


def _is_relevant_candidate(candidate: WebSearchCandidate) -> bool:
    if candidate.candidate_type == "wechat_article":
        return True
    if candidate.provider == "official_catalog":
        return True
    text = " ".join([candidate.title, candidate.snippet]).lower()
    if candidate.title.lstrip().startswith("#") or candidate.title.count("#") >= 2 or len(candidate.title) > 120:
        return False
    if any(term.lower() in text for term in REJECTED_ANNOUNCEMENT_TERMS):
        return False
    has_recruitment_term = any(term.lower() in text for term in RECRUITMENT_TITLE_TERMS)
    if candidate.candidate_type == "news_announcement":
        return has_recruitment_term
    if not has_recruitment_term:
        return False
    parsed = urllib.parse.urlparse(candidate.canonical_url)
    host_path = f"{parsed.netloc}{parsed.path}".lower()
    return bool(source_for_url(candidate.canonical_url) or source_for_text(text) or any(term in host_path for term in RECRUITMENT_PATH_TERMS))


def _infer_company_name(candidate: WebSearchCandidate) -> str:
    if candidate.company_name:
        return candidate.company_name
    source = source_for_text(candidate.title) or source_for_url(candidate.publisher_url) or source_for_url(candidate.canonical_url)
    if source:
        return source.name
    title = re.sub(r"^[【\[].*?[】\]]\s*", "", candidate.title or "").strip()
    title = re.sub(r"^@?20\d{2}届毕业生[:：]\s*", "", title)
    prefix = re.split(r"20\d{2}(?:\s*(?:届|年|年度))?|校园招聘|校招|秋招|春招|招聘", title, maxsplit=1)[0]
    prefix = re.sub(r"(?:正式)?启动[！!：:]?$|开始啦[！!]?$|顶尖人才计划.*$", "", prefix).strip(" ：:·-|_")
    if 2 <= len(prefix) <= 36 and prefix not in {"中国", "全国", "多家", "高校", "企业", "央企", "国企", "日本", "美国"}:
        return prefix
    return ""


def _infer_recruitment_type(text: str) -> str:
    if "提前批" in text:
        return "提前批"
    if "暑期实习" in text or "实习生" in text or "实习" in text:
        return "实习"
    if "春招" in text or "春季" in text:
        return "春招"
    if "秋招" in text or "秋季" in text:
        return "秋招"
    return "校招"


def _campaign_payload_from_candidate(candidate: WebSearchCandidate) -> dict[str, Any] | None:
    company_name = _infer_company_name(candidate)
    if not company_name:
        return None
    source = source_for_text(candidate.title) or source_for_url(candidate.publisher_url) or source_for_url(candidate.canonical_url)
    evidence_source = source_for_url(candidate.publisher_url) or source_for_url(candidate.canonical_url)
    cohort_matches = re.findall(r"(20\d{2})\s*届", candidate.title or "")
    if not cohort_matches:
        cohort_matches = re.findall(r"(20\d{2})(?:年)?(?=校招|校园招聘|秋招|春招|实习)", candidate.title or "")
    source_host = urllib.parse.urlparse(candidate.publisher_url or candidate.canonical_url).netloc.lower()
    source_level = evidence_source.trust_level if evidence_source else ("S" if source_host.endswith(".gov.cn") or "sasac.gov.cn" in source_host else "B")
    status = "pending_review" if candidate.provider == "official_catalog" else "open"
    evidence = " ｜ ".join(part for part in [candidate.title, candidate.publisher, candidate.snippet] if part)
    return {
        "company_name": company_name,
        "company_aliases": list(source.aliases) if source else [],
        "company_type": source.company_type if source else "unknown",
        "industry": source.industry if source else "unknown",
        "company_source_level": source.trust_level if source else source_level,
        "official_site": source.url if source else candidate.publisher_url or None,
        "recruit_site": source.url if source else None,
        "campaign_name": candidate.title or f"{company_name} 招聘公告",
        "recruitment_type": _infer_recruitment_type(candidate.title),
        "target_cohort": f"{cohort_matches[-1]}届" if cohort_matches else None,
        "status": status,
        "start_date": candidate.published_at[:10] if candidate.published_at else None,
        "deadline": None,
        "degree_min": "bachelor",
        "apply_url": source.url if source else None,
        "source_url": candidate.canonical_url,
        "source_level": source_level,
        "description": candidate.snippet or f"{candidate.publisher} 发布的招聘公告。",
        "evidence_text": evidence,
        "confidence": 0.86 if source else 0.74,
    }


def _import_candidate(candidate: WebSearchCandidate, freshness_days: int) -> None:
    if candidate.status == "stale":
        candidate.error = candidate.reject_reason
        return
    if not _is_relevant_candidate(candidate):
        candidate.status = "rejected"
        candidate.reject_reason = "not_a_recruitment_result"
        return
    if candidate.candidate_type == "wechat_article":
        imported = ingest_url(
            candidate.canonical_url,
            source=f"{candidate.provider}_plain_search",
            source_query=candidate.source_query,
            max_age_days=freshness_days,
        )
        candidate.imported = True
        candidate.article_id = int(imported.get("id") or 0)
        return
    if candidate.candidate_type == "news_announcement":
        payload = _campaign_payload_from_candidate(candidate)
        if not payload:
            candidate.status = "rejected"
            candidate.reject_reason = "company_not_identified"
            return
        imported = import_discovered_campaign(payload)
        candidate.company_name = payload["company_name"]
        candidate.campaign_id = int(imported["campaign_id"])
        candidate.signal_id = int(imported["signal_id"])
        candidate.job_ids = []
        candidate.imported = True
        return
    candidate.signal_id = _create_signal_from_candidate(candidate)
    if candidate.source_scope in {"official", "all"}:
        try:
            candidate.job_ids = _import_jobs_from_candidate(candidate)
        except Exception as exc:
            candidate.job_ids = []
            candidate.error = f"岗位抽取失败：{exc}"
    if not candidate.job_ids:
        payload = _campaign_payload_from_candidate(candidate)
        if payload:
            imported = import_discovered_campaign(payload)
            candidate.company_name = payload["company_name"]
            candidate.campaign_id = int(imported["campaign_id"])
    candidate.imported = True


def _should_fetch_jobs(candidate: WebSearchCandidate) -> bool:
    if candidate.candidate_type != "web_signal":
        return False
    if candidate.source_scope not in {"official", "all"}:
        return False
    parsed = urllib.parse.urlparse(candidate.canonical_url)
    host_path = f"{parsed.netloc}{parsed.path}".lower()
    if candidate.provider == "official_catalog":
        return True
    return any(token in host_path for token in ["zhaopin", "career", "careers", "campus", "job", "recruit", "hotjob"])


def _fetch_job_page_html(url: str, timeout: int = 14) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": os.getenv("JOB_RADAR_BROWSER_USER_AGENT", "Mozilla/5.0 JobRadar personal local job extractor"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with _open_url(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _is_chnenergy_recruit_url(url: str) -> bool:
    return urllib.parse.urlparse(url).netloc.lower().endswith(CHNENERGY_RECRUIT_HOST)


def _chnenergy_link_priority(url: str, title: str) -> int:
    if "/annc/showggStationList" in url:
        return 0
    title = title or ""
    if "笔试" in title or "通知" in title:
        return 8
    if "直招" in title or "春季招聘" in title:
        return 1
    if "高校毕业生" in title:
        return 2
    if "专项招聘" in title or "乡村振兴" in title:
        return 3
    if "社会招聘" in title:
        return 6
    return 5


def _extract_chnenergy_follow_urls(html_text: str, base_url: str, limit: int = 8) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for order, (url, title) in enumerate(_extract_links(html_text, base_url)):
        if not _is_chnenergy_recruit_url(url):
            continue
        if "/annc/showggStationList" not in url and "/annc/showgg?" not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        ranked.append((_chnenergy_link_priority(url, title), order, url))
    ranked.sort()
    return [url for _, _, url in ranked[:limit]]


def _linked_job_pages(start_url: str, html_text: str, max_pages: int = 8) -> list[tuple[str, str]]:
    if not _is_chnenergy_recruit_url(start_url):
        return []
    pages: list[tuple[str, str]] = []
    seen = {start_url}
    queue = _extract_chnenergy_follow_urls(html_text, start_url, limit=max_pages)
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            body = _fetch_job_page_html(url, timeout=12)
        except Exception:
            continue
        pages.append((url, body))
        nested = [item for item in _extract_chnenergy_follow_urls(body, url, limit=max_pages) if item not in seen]
        station_urls = [item for item in nested if "/annc/showggStationList" in item]
        detail_urls = [item for item in nested if "/annc/showgg?" in item]
        queue = station_urls + queue + detail_urls
    return pages


def _import_jobs_from_candidate(candidate: WebSearchCandidate) -> list[int]:
    if not _should_fetch_jobs(candidate):
        return []
    if candidate.canonical_url.lower().endswith(".pdf"):
        return []
    body = _fetch_job_page_html(candidate.canonical_url, timeout=16)
    default_company = _official_source_name_for_url(candidate.canonical_url) or candidate.title or "未知公司"
    source_level = _source_level_for_scope(candidate.source_scope, candidate.canonical_url)
    pages = [(candidate.canonical_url, body), *_linked_job_pages(candidate.canonical_url, body)]
    jobs: list[dict[str, Any]] = []
    seen_jobs: set[tuple[str, str]] = set()
    for page_url, page_body in pages:
        for job in extract_jobs_from_html(
            page_body,
            source_url=page_url,
            default_company=default_company,
            source_level=source_level,
            max_jobs=20,
        ):
            key = (job.get("company_name") or "", job.get("title") or "")
            if key in seen_jobs:
                continue
            seen_jobs.add(key)
            jobs.append(job)
            if len(jobs) >= 20:
                break
        if len(jobs) >= 20:
            break
    job_ids: list[int] = []
    seen_job_ids: set[int] = set()
    for job in jobs:
        result = import_scraped_job(job)
        job_id = int(result["job_id"])
        if job_id not in seen_job_ids:
            seen_job_ids.add(job_id)
            job_ids.append(job_id)
    return job_ids


def _job_summary(job_id: int) -> dict[str, Any] | None:
    job = get_job(job_id)
    if not job:
        return None
    return {
        "id": job["id"],
        "title": job["title"],
        "company_name": (job.get("company") or {}).get("name") or "未知公司",
        "cities": job.get("cities") or [],
        "deadline": (job.get("campaign") or {}).get("deadline"),
        "campaign_name": (job.get("campaign") or {}).get("name"),
        "apply_url": job.get("apply_url"),
        "source_url": job.get("source_url"),
        "source_level": job.get("source_level"),
    }


def _collect_job_summaries(items: list[WebSearchCandidate]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in items:
        for job_id in item.job_ids or []:
            if job_id in seen:
                continue
            seen.add(job_id)
            summary = _job_summary(job_id)
            if summary:
                summaries.append(summary)
    return summaries


def auto_search_and_import(keyword: str, provider: str = "all", freshness_days: int = 45, max_results: int = 10, source_scope: str = "all") -> dict[str, Any]:
    providers = _provider_list(provider)
    source_scope = _normalize_source_scope(source_scope)
    all_items: list[WebSearchCandidate] = []
    provider_results: list[dict[str, Any]] = []
    if provider != "sogou" and source_scope in {"all", "official"}:
        catalog_items = fetch_curated_official_results(keyword, source_scope=source_scope, max_results=max_results)
        if catalog_items:
            run_id = _record_run("official_catalog", keyword, freshness_days)
            provider_error = ""
            try:
                for item in catalog_items:
                    try:
                        _import_candidate(item, freshness_days=freshness_days)
                    except Exception as exc:
                        item.error = str(exc)
                    _record_candidate(run_id, item, freshness_days)
                _finish_run(run_id, "finished", catalog_items)
            except Exception as exc:
                provider_error = str(exc)
                _finish_run(run_id, "failed", catalog_items, error=provider_error)
            all_items.extend(catalog_items)
            provider_results.append({
                "provider": "official_catalog",
                "run_id": run_id,
                "count": len(catalog_items),
                "imported": len([item for item in catalog_items if item.imported]),
                "jobs_imported": sum(len(item.job_ids or []) for item in catalog_items),
                "campaigns_imported": len([item for item in catalog_items if item.campaign_id]),
                "error": provider_error,
                "items": [asdict(item) for item in catalog_items],
            })
    for name in providers:
        run_id = _record_run(name, keyword, freshness_days)
        items: list[WebSearchCandidate] = []
        provider_error = ""
        try:
            items = fetch_search_results(name, keyword, freshness_days=freshness_days, max_results=max_results, source_scope=source_scope)
            for item in items:
                try:
                    _import_candidate(item, freshness_days=freshness_days)
                except Exception as exc:
                    item.error = str(exc)
                _record_candidate(run_id, item, freshness_days)
            _finish_run(run_id, "finished", items)
        except Exception as exc:
            provider_error = str(exc)
            _finish_run(run_id, "failed", items, error=provider_error)
        all_items.extend(items)
        provider_results.append({
            "provider": name,
            "run_id": run_id,
            "count": len(items),
            "imported": len([item for item in items if item.imported]),
            "jobs_imported": sum(len(item.job_ids or []) for item in items),
            "campaigns_imported": len([item for item in items if item.campaign_id]),
            "error": provider_error,
            "items": [asdict(item) for item in items],
        })
    return {
        "keyword": keyword,
        "provider": provider,
        "source_scope": source_scope,
        "count": len(all_items),
        "imported": len([item for item in all_items if item.imported]),
        "jobs_imported": sum(len(item.job_ids or []) for item in all_items),
        "campaigns_imported": len([item for item in all_items if item.campaign_id]),
        "opportunities_imported": sum(len(item.job_ids or []) for item in all_items) + len([item for item in all_items if item.campaign_id]),
        "jobs": _collect_job_summaries(all_items),
        "providers": provider_results,
        "items": [asdict(item) for item in all_items],
    }
