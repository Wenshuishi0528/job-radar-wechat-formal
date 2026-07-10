from __future__ import annotations

from typing import Any

from .matchers import DEGREE_RANK


SKILL_TERMS = (
    "Python", "Java", "C++", "Go", "JavaScript", "TypeScript", "SQL", "Linux",
    "React", "Vue", "Spring", "机器学习", "深度学习", "大模型", "算法", "数据分析",
    "数据科学", "人工智能", "计算机", "软件工程", "嵌入式", "芯片", "集成电路",
    "通信", "自动化", "电气", "机械", "材料", "化工", "能源", "金融", "会计",
    "财务", "法务", "人力资源", "产品", "运营", "市场", "营销", "供应链", "物流",
    "英语", "日语", "德语", "科研", "项目管理",
)

FAMILY_HINTS = {
    "技术": ("Python", "Java", "C++", "Go", "JavaScript", "TypeScript", "SQL", "Linux", "React", "Vue", "Spring", "算法", "机器学习", "深度学习", "大模型", "计算机", "软件工程", "嵌入式"),
    "产品": ("产品", "项目管理", "数据分析"),
    "运营": ("运营", "数据分析", "英语"),
    "市场": ("市场", "营销", "英语"),
    "金融": ("金融", "会计", "财务", "数据分析"),
    "职能": ("会计", "财务", "法务", "人力资源", "项目管理"),
    "管培生": ("项目管理", "运营", "市场", "英语"),
}


def _contains(text: str, term: str) -> bool:
    return term.lower() in text.lower()


def extract_resume_keywords(resume_text: str) -> list[str]:
    return [term for term in SKILL_TERMS if _contains(resume_text, term)]


def infer_resume_families(resume_text: str) -> list[str]:
    keywords = set(extract_resume_keywords(resume_text))
    ranked = sorted(
        ((family, len(keywords.intersection(hints))) for family, hints in FAMILY_HINTS.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    return [family for family, count in ranked if count > 0][:3]


def match_opportunity(
    resume_text: str,
    opportunity: dict[str, Any],
    *,
    target_cities: list[str] | None = None,
    preferred_job_families: list[str] | None = None,
    degree: str | None = None,
) -> dict[str, Any]:
    target_cities = [value.strip() for value in (target_cities or []) if value.strip()]
    preferred_job_families = [value.strip() for value in (preferred_job_families or []) if value.strip()]
    resume_keywords = extract_resume_keywords(resume_text)
    inferred_families = infer_resume_families(resume_text)
    desired_families = preferred_job_families or inferred_families
    opportunity_text = " ".join([
        opportunity.get("company_name") or "",
        opportunity.get("industry") or "",
        opportunity.get("title") or "",
        opportunity.get("campaign_name") or "",
        " ".join(opportunity.get("job_families") or []),
        " ".join(opportunity.get("majors") or []),
        " ".join(opportunity.get("cities") or []),
    ])

    score = 0.15
    reasons: list[str] = []
    gaps: list[str] = []

    if opportunity.get("record_type") == "job":
        score += 0.05
        reasons.append("该记录已抽取到明确岗位名称。")
    else:
        gaps.append("当前只有招聘项目公告，岗位明细需打开官网确认。")

    matched_keywords = [term for term in resume_keywords if _contains(opportunity_text, term)]
    if matched_keywords:
        score += min(0.35, 0.06 * len(matched_keywords))
        reasons.append(f"简历关键词命中：{'、'.join(matched_keywords[:6])}。")
    elif resume_keywords:
        score -= 0.05
        gaps.append("当前公告字段未命中简历中的主要技能关键词。")
    else:
        gaps.append("简历中没有识别到可用于匹配的技能关键词。")

    item_families = opportunity.get("job_families") or []
    family_matches = [family for family in desired_families if family in item_families or _contains(opportunity_text, family)]
    if family_matches:
        score += 0.15
        reasons.append(f"岗位方向匹配：{'、'.join(family_matches)}。")
    elif desired_families:
        score -= 0.04
        gaps.append(f"未匹配目标岗位方向：{'、'.join(desired_families)}。")

    cities = opportunity.get("cities") or []
    if target_cities and cities:
        city_matches = [city for city in target_cities if city in cities or "全国" in cities]
        if city_matches:
            score += 0.10
            reasons.append(f"目标城市匹配：{'、'.join(city_matches)}。")
        else:
            score -= 0.06
            gaps.append("招聘地点不在目标城市中。")
    elif target_cities:
        gaps.append("公告未提供可核验的城市信息。")

    required_degree = opportunity.get("degree_min")
    if degree in DEGREE_RANK and required_degree in DEGREE_RANK:
        if DEGREE_RANK[degree] >= DEGREE_RANK[required_degree]:
            score += 0.07
            reasons.append("学历层级满足已解析的最低要求。")
        else:
            score -= 0.22
            gaps.append("学历层级低于已解析的最低要求。")

    source_level = opportunity.get("source_level") or "C"
    if source_level in {"S", "A"}:
        score += 0.04
        reasons.append(f"来源可信度为 {source_level} 级。")
    elif source_level == "B":
        score += 0.02
    else:
        gaps.append("来源等级较低，投递前需要复核。")

    if opportunity.get("status") == "open":
        score += 0.03
    elif opportunity.get("status") == "pending_review":
        gaps.append("开放状态仍待确认。")

    score = max(0.0, min(1.0, score))
    if score >= 0.70:
        status = "high"
    elif score >= 0.48:
        status = "medium"
    else:
        status = "low"
    return {
        "score": round(score, 3),
        "status": status,
        "reasons": reasons,
        "gaps": gaps,
        "matched_keywords": matched_keywords,
        "inferred_job_families": inferred_families,
    }
