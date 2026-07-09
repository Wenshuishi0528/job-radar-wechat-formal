from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .written_test import classify_written_test

CITY_KEYWORDS = [
    "北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "成都", "武汉", "西安", "天津", "重庆",
    "青岛", "厦门", "长沙", "合肥", "宁波", "无锡", "珠海", "佛山", "全国", "远程"
]

JOB_FAMILY_KEYWORDS = {
    "产品": ["产品", "产品经理", "数据产品", "AI产品"],
    "技术": ["研发", "算法", "工程师", "开发", "测试", "前端", "后端", "客户端", "嵌入式"],
    "运营": ["运营", "用户运营", "内容运营", "活动运营"],
    "市场": ["市场", "品牌", "营销", "增长"],
    "金融": ["投行", "研究", "交易", "风控", "量化", "金融"],
    "职能": ["人力", "财务", "法务", "行政", "党务"],
    "管培生": ["管培", "管理培训生", "储备干部"],
}

@dataclass
class ExtractedField:
    value: Any
    evidence: str
    confidence: float

@dataclass
class ExtractedNotice:
    company_name: str
    campaign_name: str
    job_title: str
    recruitment_type: str = "unknown"
    target_cohort: str | None = None
    domestic_grad_start: str | None = None
    domestic_grad_end: str | None = None
    overseas_grad_start: str | None = None
    overseas_grad_end: str | None = None
    accepts_overseas: bool | None = None
    deadline: str | None = None
    cities: list[str] = field(default_factory=list)
    degree_min: str = "bachelor"
    job_family: str = "unknown"
    apply_url: str | None = None
    source_url: str | None = None
    source_level: str = "C"
    written_test_status: str = "unknown"
    written_test_burden: int = 5
    written_test_confidence: float = 0.2
    written_test_evidence: str = ""
    evidence: dict[str, ExtractedField] = field(default_factory=dict)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _context(text: str, start: int, end: int, window: int = 60) -> str:
    return text[max(0, start - window): min(len(text), end + window)].strip()


def extract_cohort(text: str) -> ExtractedField | None:
    m = re.search(r"(20\d{2})\s*届", text)
    if not m:
        return None
    return ExtractedField(f"{m.group(1)}届", _context(text, m.start(), m.end()), 0.8)


def infer_recruitment_type(text: str) -> str:
    compact = _compact(text)
    if "提前批" in compact:
        return "提前批"
    if "春招" in compact or "春季招聘" in compact or "春季校园招聘" in compact:
        return "春招"
    if "秋招" in compact or "秋季招聘" in compact or "秋季校园招聘" in compact:
        return "秋招"
    if "补录" in compact:
        return "补录"
    if "实习" in compact:
        return "实习"
    if "校园招聘" in compact:
        return "校招"
    return "unknown"


def extract_deadline(text: str) -> ExtractedField | None:
    patterns = [
        r"(?:截止|报名截止|投递截止|网申截止)[^0-9]{0,12}(20\d{2})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})",
        r"(20\d{2})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})[^。；\n]{0,12}(?:截止|结束)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            value = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return ExtractedField(value, _context(text, m.start(), m.end()), 0.75)
    return None


def extract_grad_range(text: str, overseas: bool) -> tuple[ExtractedField | None, ExtractedField | None]:
    prefix = r"(?:海外|境外|留学生|海归|港澳台|境内外|海内外)" if overseas else r"(?:国内|境内|中国大陆|大陆)"
    pattern = prefix + r"[^。；\n]{0,80}?(20\d{2})\s*[年\-/\.]\s*(\d{1,2})\s*月?[^0-9]{0,12}(?:至|到|-|—|~)[^0-9]{0,12}(20\d{2})\s*[年\-/\.]\s*(\d{1,2})\s*月?"
    m = re.search(pattern, text)
    if not m and overseas:
        pattern = r"(20\d{2})\s*[年\-/\.]\s*(\d{1,2})\s*月?[^0-9]{0,12}(?:至|到|-|—|~)[^0-9]{0,12}(20\d{2})\s*[年\-/\.]\s*(\d{1,2})\s*月?[^。；\n]{0,40}(?:海外|境外|留学生|海归|海内外)"
        m = re.search(pattern, text)
    if not m:
        return None, None
    start = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    end = f"{int(m.group(3)):04d}-{int(m.group(4)):02d}"
    ev = _context(text, m.start(), m.end())
    return ExtractedField(start, ev, 0.72), ExtractedField(end, ev, 0.72)


def extract_accepts_overseas(text: str) -> ExtractedField | None:
    compact = _compact(text)
    positive = ["海外", "境外", "留学生", "海归", "海内外", "境内外"]
    negative = ["仅限国内", "不接受海外", "海外学历不可", "留学生不可"]
    for word in negative:
        if word in compact:
            return ExtractedField(False, word, 0.8)
    for word in positive:
        pos = compact.find(word)
        if pos >= 0:
            return ExtractedField(True, compact[max(0, pos - 40): pos + 80], 0.65)
    return None


def extract_cities(text: str) -> list[str]:
    found: list[str] = []
    for city in CITY_KEYWORDS:
        if city in text and city not in found:
            found.append(city)
    return found


def infer_degree(text: str) -> str:
    compact = _compact(text)
    if "博士" in compact:
        return "phd"
    if "硕士" in compact or "研究生" in compact:
        return "master"
    if "本科" in compact:
        return "bachelor"
    if "大专" in compact or "专科" in compact:
        return "associate"
    return "bachelor"


def infer_job_family(title: str, text: str) -> str:
    haystack = title + "\n" + text[:1000]
    for family, keywords in JOB_FAMILY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return family
    return "unknown"


def extract_notice(
    *,
    company_name: str,
    job_title: str,
    text: str,
    source_url: str | None = None,
    source_level: str = "C",
) -> ExtractedNotice:
    written = classify_written_test(text)
    cohort = extract_cohort(text)
    deadline = extract_deadline(text)
    domestic_start, domestic_end = extract_grad_range(text, overseas=False)
    overseas_start, overseas_end = extract_grad_range(text, overseas=True)
    accepts_overseas = extract_accepts_overseas(text)
    recruitment_type = infer_recruitment_type(text)

    campaign_name = f"{cohort.value if cohort else '未知届别'}{recruitment_type if recruitment_type != 'unknown' else '招聘项目'}"
    evidence: dict[str, ExtractedField] = {}
    if cohort:
        evidence["target_cohort"] = cohort
    if deadline:
        evidence["deadline"] = deadline
    if domestic_start and domestic_end:
        evidence["domestic_grad_range"] = ExtractedField(
            f"{domestic_start.value}至{domestic_end.value}", domestic_start.evidence, 0.72
        )
    if overseas_start and overseas_end:
        evidence["overseas_grad_range"] = ExtractedField(
            f"{overseas_start.value}至{overseas_end.value}", overseas_start.evidence, 0.72
        )
    if accepts_overseas:
        evidence["accepts_overseas"] = accepts_overseas
    evidence["written_test_status"] = ExtractedField(written.status, written.evidence, written.confidence)

    return ExtractedNotice(
        company_name=company_name.strip(),
        campaign_name=campaign_name,
        job_title=job_title.strip() or "待命名岗位",
        recruitment_type=recruitment_type,
        target_cohort=cohort.value if cohort else None,
        domestic_grad_start=domestic_start.value if domestic_start else None,
        domestic_grad_end=domestic_end.value if domestic_end else None,
        overseas_grad_start=overseas_start.value if overseas_start else None,
        overseas_grad_end=overseas_end.value if overseas_end else None,
        accepts_overseas=accepts_overseas.value if accepts_overseas else None,
        deadline=deadline.value if deadline else None,
        cities=extract_cities(text),
        degree_min=infer_degree(text),
        job_family=infer_job_family(job_title, text),
        source_url=source_url,
        source_level=source_level,
        written_test_status=written.status,
        written_test_burden=written.burden,
        written_test_confidence=written.confidence,
        written_test_evidence=written.evidence,
        evidence=evidence,
    )
