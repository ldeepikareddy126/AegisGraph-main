"""Deterministic disclosure policy kept separate from behavioral risk scoring."""
from __future__ import annotations

import re
from typing import Any, Dict


_HIGH_SENSITIVITY = re.compile(
    r"\b(?:ssn|social security(?: number)?s?|"
    r"(?:home|personal) (?:address|phone|telephone|email|contact details?)|"
    r"phone numbers?|telephone numbers?|email addresses?|"
    r"passwords?|credentials?|bank account numbers?|"
    r"dates? of birth|birth dates?|personal identifying information|pii)\b",
    re.IGNORECASE,
)
_SENSITIVE_DATA = re.compile(
    r"\b(?:salary|salaries|compensation|bonus(?:es)?|severance|payroll|"
    r"confidential|restricted|proprietary|trade secrets?|insider information|"
    r"financial amounts?|raw records?)\b",
    re.IGNORECASE,
)
_DISCLOSURE_INTENT = re.compile(
    r"\b(?:show|list|give|provide|tell me|find|identify|reveal|dump|export|"
    r"share|retrieve|search(?:\s+for)?|summari[sz]e|describe|what|who|which|"
    r"every|all|each|verbatim|raw|exact|complete)\b",
    re.IGNORECASE,
)
_BULK_INTENT = re.compile(
    r"\b(?:list|every|all(?!\s+about\b)|each|dump|export|verbatim|raw|exact|complete|"
    r"bulk|all employees|all records)\b",
    re.IGNORECASE,
)
_SAFE_GUIDANCE = re.compile(
    r"\b(?:how to|how do i|ways to|guidance on|best practices for)\s+"
    r"(?:protect|secure|redact|detect|prevent|safeguard|comply)\b",
    re.IGNORECASE,
)
_SAFE_DEFINITION = re.compile(
    r"\b(?:what (?:is|are)|define|meaning of|what does)\s+"
    r"(?:an?\s+)?(?:ssn|social security(?: number)?|pii|"
    r"passwords?|credentials?)\b",
    re.IGNORECASE,
)


def disclosure_decision(query: str, behavioral_level: str) -> Dict[str, Any]:
    """Return the disclosure tier without changing the behavioral risk score.

    Direct requests for highly sensitive identifiers or credentials are
    withheld at HIGH. Other actionable sensitive-data requests are redacted
    at MEDIUM; enumerative requests for such data are withheld at HIGH.
    """
    if behavioral_level == "HIGH":
        return {
            "level": "HIGH",
            "triggered": False,
            "reason": "Behavioral risk reached HIGH; high-risk disclosure policy applies.",
        }

    if _SAFE_GUIDANCE.search(query) or _SAFE_DEFINITION.search(query):
        return {"level": behavioral_level, "triggered": False, "reason": ""}

    high_match = _HIGH_SENSITIVITY.search(query)
    sensitive_match = _SENSITIVE_DATA.search(query)
    has_intent = bool(_DISCLOSURE_INTENT.search(query))
    bulk = bool(_BULK_INTENT.search(query))

    if high_match and has_intent:
        return {
            "level": "HIGH",
            "triggered": True,
            "reason": "Direct request for personal identifiers or credentials.",
        }
    if sensitive_match and has_intent and bulk:
        return {
            "level": "HIGH",
            "triggered": True,
            "reason": "Bulk or verbatim request for sensitive business data.",
        }
    if (high_match or sensitive_match) and has_intent:
        return {
            "level": "MEDIUM",
            "triggered": True,
            "reason": "Sensitive-data request requires redacted disclosure.",
        }
    return {"level": behavioral_level, "triggered": False, "reason": ""}
