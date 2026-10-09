"""Intent detection and presentation for non-identifying graph aggregates."""
from __future__ import annotations

import re
from typing import Any, Dict


_EMPLOYEE_COUNT_REQUEST = re.compile(
    r"\b(?:how many\s+(?:people|employees|staff|personnel)|"
    r"(?:number|count|total)\s+of\s+(?:all\s+)?(?:employees|staff|personnel|people)|"
    r"(?:employee|staff|personnel|workforce)\s+(?:headcount|count|total))\b",
    re.IGNORECASE,
)
_EMPLOYEE_ROSTER_REQUEST = re.compile(
    r"\b(?:list|enumerate|identify|name|show|provide|give)\b.{0,40}"
    r"\b(?:all|every|each)\s+(?:of\s+)?(?:the\s+)?"
    r"(?:employees|staff|personnel)\b",
    re.IGNORECASE,
)
_EMPLOYEE_ROSTER_NOUN = re.compile(
    r"\b(?:employee|staff|personnel|workforce)\s+"
    r"(?:roster|directory|list)\b",
    re.IGNORECASE,
)
_NUMERIC_EMPLOYEE_CLAIM = re.compile(
    r"\b\d[\d,]*\s+(?:distinct\s+)?"
    r"(?:employees?|employee\s+(?:records?|entries?)|"
    r"staff(?:\s+members?)?|personnel|people)\b",
    re.IGNORECASE,
)


def requests_employee_aggregate(query: str) -> bool:
    """Match workforce-count questions and requests to enumerate the full roster."""
    return bool(
        _EMPLOYEE_COUNT_REQUEST.search(query)
        or _EMPLOYEE_ROSTER_REQUEST.search(query)
        or _EMPLOYEE_ROSTER_NOUN.search(query)
    )


def append_employee_aggregate(
    answer: Dict[str, Any], count: int, disclosure_level: str
) -> Dict[str, Any]:
    """Append a qualified aggregate only when the disclosure tier permits it."""
    if disclosure_level == "HIGH":
        return answer
    if count < 0:
        raise ValueError("Employee aggregate count cannot be negative.")

    answer = dict(answer)
    summary = str(answer.get("summary") or "").strip()
    record_label = "employee record" if count == 1 else "employee records"
    canonical_count = f"{count} distinct {record_label}"
    has_employee_count = bool(_NUMERIC_EMPLOYEE_CLAIM.search(summary))
    summary = _NUMERIC_EMPLOYEE_CLAIM.sub(canonical_count, summary)
    fact = (
        (
            "That figure is the configured graph's dataset count, not a "
            "verified current workforce roster."
            if has_employee_count
            else f"The configured graph currently marks {canonical_count}; "
            "this is a dataset count, not a verified current workforce roster."
        )
    )
    if disclosure_level == "MEDIUM":
        fact += " Individual names are withheld at this disclosure level."
    answer["summary"] = f"{summary} {fact}".strip()
    return answer
