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
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from .database import get_connection
from .extraction import CITY_KEYWORDS, infer_job_family
from .repository import import_scraped_job
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
    job_ids: list[int] | None = None
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
    compact = _compact_keyword(keyword)
    candidates: list[WebSearchCandidate] = []
    seen: set[str] = set()
    for source in CURATED_OFFICIAL_SOURCES:
        aliases = [_compact_keyword(alias) for alias in source["aliases"]]
        if not any(alias and alias in compact for alias in aliases):
            continue
        for title, url in source["urls"]:
            item = _candidate_from_url(
                url,
                "official_catalog",
                keyword,
                title=title,
                snippet=f"{source['name']}（{source['industry']}）官方招聘入口候选。",
                source_scope="official",
            )
            if item and item.canonical_url not in seen:
                seen.add(item.canonical_url)
                candidates.append(item)
                if len(candidates) >= max_results:
                    return candidates
    return candidates


def _official_source_name_for_url(url: str) -> str:
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


def _extract_href_candidates(provider: str, html_text: str) -> list[tuple[str, str]]:
    base_url = "https://www.google.com" if provider == "google" else "https://www.bing.com"
    candidates: list[tuple[str, str]] = []
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_text or "", flags=re.I | re.S):
        href = match.group(1)
        href = html.unescape(href)
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        full = urllib.parse.urljoin(base_url, href)
        candidates.append((full, _text_from_html(match.group(2))))
    return candidates


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


def extract_jobs_from_html(html_text: str, source_url: str, default_company: str = "未知公司", source_level: str = "A", max_jobs: int = 20) -> list[dict[str, Any]]:
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
    host = urllib.parse.urlparse(url).netloc.lower()
    if source_scope == "official" or any(token in host for token in ["career", "campus", "jobs", "talent"]):
        return "A"
    if source_scope in {"university", "wechat"}:
        return "B"
    return "C"


def _import_candidate(candidate: WebSearchCandidate, freshness_days: int) -> None:
    if candidate.status == "stale":
        candidate.error = candidate.reject_reason
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
    candidate.signal_id = _create_signal_from_candidate(candidate)
    if candidate.source_scope in {"official", "all"}:
        try:
            candidate.job_ids = _import_jobs_from_candidate(candidate)
        except Exception as exc:
            candidate.job_ids = []
            candidate.error = f"岗位抽取失败：{exc}"
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


def _import_jobs_from_candidate(candidate: WebSearchCandidate) -> list[int]:
    if not _should_fetch_jobs(candidate):
        return []
    if candidate.canonical_url.lower().endswith(".pdf"):
        return []
    request = urllib.request.Request(
        candidate.canonical_url,
        headers={
            "User-Agent": os.getenv("JOB_RADAR_BROWSER_USER_AGENT", "Mozilla/5.0 JobRadar personal local job extractor"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with _open_url(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset, errors="replace")
    default_company = _official_source_name_for_url(candidate.canonical_url) or candidate.title or "未知公司"
    jobs = extract_jobs_from_html(
        body,
        source_url=candidate.canonical_url,
        default_company=default_company,
        source_level=_source_level_for_scope(candidate.source_scope, candidate.canonical_url),
        max_jobs=20,
    )
    job_ids: list[int] = []
    seen_job_ids: set[int] = set()
    for job in jobs:
        result = import_scraped_job(job)
        job_id = int(result["job_id"])
        if job_id not in seen_job_ids:
            seen_job_ids.add(job_id)
            job_ids.append(job_id)
    return job_ids


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
        "providers": provider_results,
        "items": [asdict(item) for item in all_items],
    }
