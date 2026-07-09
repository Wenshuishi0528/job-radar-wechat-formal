from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .written_test import UNKNOWN

DEGREE_RANK = {
    "associate": 1,
    "bachelor": 2,
    "master": 3,
    "phd": 4,
}

@dataclass
class MatchResult:
    status: str
    score: float
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "risks": self.risks,
            "blockers": self.blockers,
        }


def parse_year_month(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    value = value.strip().replace(".", "-").replace("/", "-")
    parts = value.split("-")
    if len(parts) < 2:
        return None
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError:
        return None
    if year < 2000 or month < 1 or month > 12:
        return None
    return year, month


def year_month_to_int(value: str | None) -> int | None:
    parsed = parse_year_month(value)
    if parsed is None:
        return None
    return parsed[0] * 12 + parsed[1]


def in_year_month_range(value: str | None, start: str | None, end: str | None) -> bool | None:
    current = year_month_to_int(value)
    if current is None:
        return None
    start_i = year_month_to_int(start)
    end_i = year_month_to_int(end)
    if start_i is None or end_i is None:
        return None
    return start_i <= current <= end_i


def degree_ok(user_degree: str | None, min_degree: str | None) -> bool | None:
    if not user_degree or not min_degree:
        return None
    user_rank = DEGREE_RANK.get(user_degree)
    min_rank = DEGREE_RANK.get(min_degree)
    if user_rank is None or min_rank is None:
        return None
    return user_rank >= min_rank


def _city_match(profile: dict[str, Any], job: dict[str, Any]) -> bool | None:
    targets = profile.get("target_cities") or []
    cities = job.get("cities") or []
    if isinstance(targets, str):
        targets = [targets]
    if not targets or "全国" in targets or "不限" in targets:
        return None
    if not cities:
        return None
    return bool(set(targets).intersection(set(cities)))


def _graduation_match(profile: dict[str, Any], campaign: dict[str, Any]) -> tuple[str, str]:
    region = profile.get("school_region", "unknown")
    graduation = profile.get("graduation_date")

    if not graduation:
        return "unknown", "用户没有填写毕业年月。"

    if region == "overseas":
        accepts = campaign.get("accepts_overseas")
        if accepts is False or accepts == 0:
            return "not_eligible", "该招聘项目没有显示接受海外学历背景。"
        result = in_year_month_range(graduation, campaign.get("overseas_grad_start"), campaign.get("overseas_grad_end"))
        if result is True:
            return "eligible", f"海外毕业时间匹配：{graduation} 位于 {campaign.get('overseas_grad_start')} 至 {campaign.get('overseas_grad_end')}。"
        if result is False:
            return "not_eligible", f"海外毕业时间不匹配：要求 {campaign.get('overseas_grad_start')} 至 {campaign.get('overseas_grad_end')}，用户是 {graduation}。"
        if accepts is True or accepts == 1:
            return "maybe", "该项目显示接受海外背景，但没有解析到明确海外毕业时间范围。"
        return "unknown", "没有解析到海外毕业时间规则。"

    if region in {"domestic", "hmt"}:
        result = in_year_month_range(graduation, campaign.get("domestic_grad_start"), campaign.get("domestic_grad_end"))
        if result is True:
            return "eligible", f"毕业时间匹配：{graduation} 位于 {campaign.get('domestic_grad_start')} 至 {campaign.get('domestic_grad_end')}。"
        if result is False:
            return "not_eligible", f"毕业时间不匹配：要求 {campaign.get('domestic_grad_start')} 至 {campaign.get('domestic_grad_end')}，用户是 {graduation}。"
        return "unknown", "没有解析到国内或港澳台毕业时间规则。"

    return "unknown", "学校地区未知，无法判断毕业时间。"


def match_job(profile: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    campaign = job.get("campaign") or {}
    process = job.get("process_rule") or {}
    result = MatchResult(status="eligible", score=0.5)

    grad_status, grad_reason = _graduation_match(profile, campaign)
    if grad_status == "eligible":
        result.reasons.append(grad_reason)
        result.score += 0.25
    elif grad_status == "maybe":
        result.risks.append(grad_reason)
        result.status = "maybe"
        result.score += 0.05
    elif grad_status == "not_eligible":
        result.blockers.append(grad_reason)
        result.status = "not_eligible"
        result.score -= 0.3
    else:
        result.risks.append(grad_reason)
        result.status = "unknown"

    degree_result = degree_ok(profile.get("degree"), job.get("degree_min") or campaign.get("degree_min"))
    if degree_result is True:
        result.reasons.append("学历层级满足最低要求。")
        result.score += 0.12
    elif degree_result is False:
        result.blockers.append("学历层级低于岗位最低要求。")
        result.status = "not_eligible"
        result.score -= 0.25
    else:
        result.risks.append("学历要求没有足够信息，需查看原文。")

    city_result = _city_match(profile, job)
    if city_result is True:
        result.reasons.append("岗位城市匹配目标城市。")
        result.score += 0.08
    elif city_result is False:
        result.risks.append("岗位城市不在目标城市中。")
        if result.status == "eligible":
            result.status = "maybe"
        result.score -= 0.05
    else:
        result.risks.append("城市偏好未设置或岗位城市不完整。")

    max_burden = profile.get("max_written_test_burden")
    burden = process.get("written_test_burden")
    status = process.get("written_test_status", UNKNOWN)
    if max_burden is not None and burden is not None:
        try:
            max_burden_i = int(max_burden)
            burden_i = int(burden)
            if burden_i <= max_burden_i:
                result.reasons.append(f"笔试负担满足偏好：{burden_i} 分。")
                result.score += 0.12
            else:
                result.blockers.append(f"笔试负担超过偏好：岗位 {burden_i} 分，用户上限 {max_burden_i} 分。")
                result.status = "not_eligible"
                result.score -= 0.25
        except (TypeError, ValueError):
            result.risks.append("笔试负担无法判断。")
    elif status == UNKNOWN:
        result.risks.append("笔试状态未知。")

    source_level = job.get("source_level") or campaign.get("source_level") or "C"
    if source_level in {"S", "A"}:
        result.reasons.append(f"来源可信度较高：{source_level} 级。")
        result.score += 0.08
    elif source_level in {"C", "D"}:
        result.risks.append(f"来源可信度较低：{source_level} 级，建议打开原文确认。")
        result.score -= 0.05

    if result.blockers:
        result.status = "not_eligible"
    elif result.status == "eligible" and result.risks:
        result.status = "maybe"

    result.score = max(0.0, min(1.0, result.score))
    return result.to_dict()


def today_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
