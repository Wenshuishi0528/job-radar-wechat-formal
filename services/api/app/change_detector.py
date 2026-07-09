from __future__ import annotations

from typing import Any


def detect_changes(old: dict[str, Any], new: dict[str, Any], fields: list[str]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for field in fields:
        old_value = old.get(field)
        new_value = new.get(field)
        if _normalize(old_value) != _normalize(new_value):
            changes.append({
                "field_name": field,
                "old_value": _stringify(old_value),
                "new_value": _stringify(new_value),
            })
    return changes


def _normalize(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return int(value)
    return value


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
