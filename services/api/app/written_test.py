from __future__ import annotations

import re
from dataclasses import dataclass

NO_WRITTEN_TEST = "no_written_test"
NO_UNIFIED_WRITTEN_TEST = "no_unified_written_test"
ROLE_SPECIFIC_OR_OPTIONAL = "role_specific_or_optional"
ASSESSMENT_ONLY = "assessment_only"
REQUIRED = "required"
UNKNOWN = "unknown"

BURDEN_BY_STATUS = {
    NO_WRITTEN_TEST: 0,
    NO_UNIFIED_WRITTEN_TEST: 1,
    ROLE_SPECIFIC_OR_OPTIONAL: 2,
    ASSESSMENT_ONLY: 2,
    REQUIRED: 4,
    UNKNOWN: 5,
}

@dataclass(frozen=True)
class WrittenTestClassification:
    status: str
    burden: int
    confidence: float
    evidence: str


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _pick_evidence(text: str, keywords: list[str], window: int = 48) -> str:
    compact = normalize_text(text)
    for keyword in keywords:
        pos = compact.find(keyword)
        if pos >= 0:
            start = max(0, pos - window)
            end = min(len(compact), pos + len(keyword) + window)
            return compact[start:end]
    return compact[:120]


def classify_written_test(text: str) -> WrittenTestClassification:
    """Classify written-test burden from a recruitment notice.

    This is intentionally conservative. If the source is not explicit, return unknown.
    """
    compact = normalize_text(text)
    if not compact:
        return WrittenTestClassification(UNKNOWN, BURDEN_BY_STATUS[UNKNOWN], 0.1, "")

    exception_words = ["个别", "部分", "视岗位", "另行", "单独通知", "岗位需要", "需要笔试的职位"]
    has_exception = any(word in compact for word in exception_words)

    no_unified_patterns = ["不设置统一笔试", "无统一笔试", "不安排统一笔试", "没有统一笔试"]
    if any(pattern in compact for pattern in no_unified_patterns):
        status = ROLE_SPECIFIC_OR_OPTIONAL if has_exception else NO_UNIFIED_WRITTEN_TEST
        return WrittenTestClassification(
            status,
            BURDEN_BY_STATUS[status],
            0.86 if has_exception else 0.9,
            _pick_evidence(text, no_unified_patterns + exception_words),
        )

    no_patterns = ["无需笔试", "免笔试", "不需要笔试", "直接面试", "直通面试"]
    if any(pattern in compact for pattern in no_patterns):
        status = ROLE_SPECIFIC_OR_OPTIONAL if has_exception else NO_WRITTEN_TEST
        return WrittenTestClassification(
            status,
            BURDEN_BY_STATUS[status],
            0.82 if has_exception else 0.9,
            _pick_evidence(text, no_patterns + exception_words),
        )

    required_patterns = ["在线笔试", "统一笔试", "技术笔试", "专业笔试", "笔试环节", "参加笔试", "笔试测评", "机考"]
    if any(pattern in compact for pattern in required_patterns):
        return WrittenTestClassification(
            REQUIRED,
            BURDEN_BY_STATUS[REQUIRED],
            0.88,
            _pick_evidence(text, required_patterns),
        )

    assessment_patterns = ["在线测评", "综合测评", "性格测评", "职业测评", "测评环节"]
    if any(pattern in compact for pattern in assessment_patterns):
        return WrittenTestClassification(
            ASSESSMENT_ONLY,
            BURDEN_BY_STATUS[ASSESSMENT_ONLY],
            0.72,
            _pick_evidence(text, assessment_patterns),
        )

    return WrittenTestClassification(UNKNOWN, BURDEN_BY_STATUS[UNKNOWN], 0.2, compact[:120])
