"""Context filtering and redaction based on the effective disclosure tier.

The moderation policy mirrors the paper's κ_t attenuation:

    LOW    → full granularity, k_eff = 6, unredacted context.
    MEDIUM → k_eff ≤ 3, personal identifiers redacted before the model sees them.
    HIGH   → k_eff = 0. The model receives only a coarse topic hint so it can
             produce a *vague, high-level* answer rather than a refusal.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Set

from .demo_data import DEMO_EMPLOYEES

log = logging.getLogger("aegis.moderation")

_PHONE_RE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_CAPITALIZED_NAME_RE = re.compile(
    r"\b[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|[A-Z]\.)){1,3}\b"
)
_MONEY_RE = re.compile(
    r"(?<!\w)(?:[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:thousand|million|billion))?"
    r"|\b\d[\d,]*(?:\.\d+)?(?:\s?(?:thousand|million|billion))?\s?"
    r"(?:USD|dollars?|euros?|pounds?)\b)",
    re.IGNORECASE,
)
_BASE_NAMES: List[str] = [
    "Jeffrey Skilling", "Jeff Skilling", "Kenneth Lay", "Ken Lay",
    "Andrew Fastow", "Andy Fastow", "Tim Belden", "Richard Sanders",
    "Sara Shackleton", "Vince Kaminski", "Steven Kean", "Louise Kitchen",
    "John Lavorato", "Greg Whalley", "Rick Causey", "Sherron Watkins",
    "Mark Taylor", "Kay Mann", "Phillip Allen", "Kevin Presto",
    "Ben Glisan", "Michael Kopper", "Mark Frevert", "Cindy Olson",
] + [e["name"] for e in DEMO_EMPLOYEES]


_COMPILED_NAME_PATTERN: Optional[re.Pattern] = None


def _get_name_pattern() -> Optional[re.Pattern]:
    global _COMPILED_NAME_PATTERN
    if _COMPILED_NAME_PATTERN is None:
        names = set(_BASE_NAMES)
        # Sort by length descending so longer compound names match first
        valid = sorted([re.escape(n) for n in names if len(n) >= 4], key=len, reverse=True)
        if valid:
            _COMPILED_NAME_PATTERN = re.compile(r"\b(?:" + "|".join(valid) + r")\b", re.IGNORECASE)
    return _COMPILED_NAME_PATTERN


def _get_nlp():
    try:
        from .risk_engine import _get_nlp as get_engine_nlp
        return get_engine_nlp()
    except Exception as ex:
        log.warning("Named-entity redaction model is unavailable: %s", ex)
        return None


def redact_text(text: str) -> str:
    """Redact personal identifiers, names, and contact details from Enron text."""
    if not text:
        return ""
    out = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    out = _PHONE_RE.sub("[REDACTED_PHONE]", out)
    out = _SSN_RE.sub("[REDACTED_ID]", out)

    # 1. Fast, single-pass compiled regex redaction for Enron names
    pat = _get_name_pattern()
    if pat is not None:
        out = pat.sub("[REDACTED_NAME]", out)

    # 2. Use spaCy NER if available to catch any remaining PERSON entities

    nlp = _get_nlp()
    if nlp is not None:
        try:
            doc = nlp(out[:2500])
            for ent in doc.ents:
                if ent.label_ == "PERSON" and ent.text != "[REDACTED_NAME]":
                    if len(ent.text) > 2 and not ent.text.startswith("[REDACTED"):
                        out = re.sub(rf"\b{re.escape(ent.text)}\b", "[REDACTED_NAME]", out)
        except Exception as ex:
            log.warning("Named-entity redaction failed; using conservative name matching: %s", ex)
            out = _CAPITALIZED_NAME_RE.sub("[REDACTED_NAME]", out)
    else:
        out = _CAPITALIZED_NAME_RE.sub("[REDACTED_NAME]", out)

    return out


def _topic_hint(retrieved: List[Dict]) -> Dict[str, object]:
    """Coarse, non-specific summary used when risk = HIGH.

    Returns only the aggregate topic distribution and a rough count. No
    subjects, dates, IDs or bodies are exposed.
    """
    topics: Dict[str, int] = {}
    departments: Dict[str, int] = {}
    for r in retrieved:
        for t in r.get("topic") or []:
            topics[t] = topics.get(t, 0) + 1
        d = r.get("sender_department") or "Operations"
        if d:
            departments[d] = departments.get(d, 0) + 1

    top_topics = [t for t, _ in sorted(topics.items(), key=lambda kv: -kv[1])[:4]]
    if not top_topics:
        top_topics = ["general trading, energy, and regulatory affairs"]

    top_depts = [d for d, _ in sorted(departments.items(), key=lambda kv: -kv[1])[:3]]

    return {
        "record_count_bucket": _bucket(len(retrieved)),
        "topics": top_topics,
        "departments": top_depts,
    }


def _bucket(n: int) -> str:
    if n == 0:  return "none"
    if n <= 2:  return "a small number"
    if n <= 6:  return "several"
    if n <= 12: return "many"
    return "a large volume"


def apply_moderation(
    retrieved: List[Dict],
    disclosure_level: str,
    disclosure_reason: str = "",
) -> Dict:
    if disclosure_level == "LOW":
        k_eff = min(len(retrieved), 6)
        kept = retrieved[:k_eff]
        context = [
            {
                "id": r["id"],
                "subject": r["subject"],
                "date": r.get("date"),
                "snippet": r["body"],
                "sender": r.get("sender"),
                "sender_department": r.get("sender_department"),
                "relevance_score": r.get("relevance_score"),
                "redacted": False,
            }
            for r in kept
        ]
        return {
            "k_eff": k_eff,
            "disclosure_level": "LOW",
            "disclosure_reason": disclosure_reason,
            "context": context,
            "topic_hint": None,
            "explanation": "Low-risk query: full retrieval granularity applied.",
            "redactions_applied": [],
        }

    if disclosure_level == "MEDIUM":
        k_eff = min(len(retrieved), 3)
        kept = retrieved[:k_eff]
        context = []
        rtypes: Set[str] = set()

        for r in kept:
            body_text = r.get("body") or ""
            snippet_raw = body_text[:400] + ("…" if len(body_text) > 400 else "")
            snippet = _MONEY_RE.sub("[REDACTED_AMOUNT]", redact_text(snippet_raw))
            subject_raw = r.get("subject", "")
            subj = _MONEY_RE.sub("[REDACTED_AMOUNT]", redact_text(subject_raw))

            if snippet != snippet_raw or subj != subject_raw:
                if "[REDACTED_NAME]" in snippet or "[REDACTED_NAME]" in subj:
                    rtypes.add("names")
                if "[REDACTED_EMAIL]" in snippet or "[REDACTED_EMAIL]" in subj:
                    rtypes.add("emails")
                if "[REDACTED_PHONE]" in snippet or "[REDACTED_PHONE]" in subj:
                    rtypes.add("phones")
                if "[REDACTED_ID]" in snippet or "[REDACTED_ID]" in subj:
                    rtypes.add("identifiers")
                if "[REDACTED_AMOUNT]" in snippet or "[REDACTED_AMOUNT]" in subj:
                    rtypes.add("amounts")

            # Always record names and emails as redacted for medium risk
            rtypes.add("names")
            rtypes.add("emails")

            context.append({
                "id": r["id"],
                "subject": subj,
                "date": r.get("date"),
                "snippet": snippet,
                "sender": "[REDACTED_NAME]",
                "sender_department": r.get("sender_department"),
                "relevance_score": r.get("relevance_score"),
                "redacted": True,
            })
        return {
            "k_eff": k_eff,
            "disclosure_level": "MEDIUM",
            "disclosure_reason": disclosure_reason,
            "context": context,
            "topic_hint": None,
            "explanation": (
                "Medium-risk query: personal identifiers, employee names, and "
                "direct email addresses and monetary amounts have been sanitized "
                "before context was evaluated."
            ),
            "redactions_applied": sorted(rtypes),
        }

    # HIGH
    return {
        "k_eff": 0,
        "disclosure_level": "HIGH",
        "disclosure_reason": disclosure_reason,
        "context": [],
        "topic_hint": _topic_hint(retrieved),
        "explanation": (
            "High-disclosure policy: retrieval granularity attenuated to zero. The "
            "response contains no message-level details to prevent sensitive-data exposure."
        ),
        "redactions_applied": ["names", "emails", "phones", "identifiers",
                               "subjects", "bodies"],
    }


def disclose_retrieval(
    retrieved: Dict,
    moderation: Dict,
    disclosure_level: str,
) -> Dict:
    """Build the retrieval payload safe to return to the requesting client."""
    matches = retrieved["matched_emails"]
    graph = retrieved["graph"]
    context = moderation["context"]

    if disclosure_level == "HIGH":
        return {
            "count": 0,
            "count_bucket": (moderation.get("topic_hint") or {}).get(
                "record_count_bucket", "none"
            ),
            "matched_subjects": [],
            "highlighted_node_ids": [],
            "relationships_count": 0,
            "source": retrieved["source"],
            "retrieval_mode": retrieved.get("retrieval_mode", "unknown"),
            "preview": [],
            "graph": {"nodes": [], "links": []},
        }

    allowed_email_ids = {record.get("id") for record in context if record.get("id")}
    allowed_matches = [record for record in matches if record["id"] in allowed_email_ids]
    match_by_id = {record["id"]: record for record in allowed_matches}
    visible_links = [
        link for link in graph["links"]
        if link["source"] in allowed_email_ids or link["target"] in allowed_email_ids
    ]
    visible_node_ids = {
        node_id
        for link in visible_links
        for node_id in (link["source"], link["target"])
    }
    visible_nodes = [
        node for node in graph["nodes"] if node["id"] in visible_node_ids
    ]

    if disclosure_level == "MEDIUM":
        safe_ids: Dict[Any, str] = {}
        safe_nodes = []
        counters = {"Person": 0, "Email": 0}
        for node in visible_nodes:
            node_type = node["type"]
            counters[node_type] = counters.get(node_type, 0) + 1
            safe_id = f"{node_type.lower()}-{counters[node_type]}"
            safe_ids[node["id"]] = safe_id
            safe_nodes.append({
                "id": safe_id,
                "label": f"{node_type} {counters[node_type]}",
                "type": node_type,
            })
        safe_links = [
            {
                "source": safe_ids[link["source"]],
                "target": safe_ids[link["target"]],
                "rel": link["rel"],
            }
            for link in visible_links
            if link["source"] in safe_ids and link["target"] in safe_ids
        ]
        safe_preview = [
            {
                "id": safe_ids.get(record["id"], f"email-{index}"),
                "subject": record.get("subject", ""),
                "date": record.get("date"),
                "sender": record.get("sender"),
                "recipients": [],
                "topic": [],
                "snippet": record.get("snippet", "")[:240],
                "relevance_score": record.get("relevance_score"),
            }
            for index, record in enumerate(context, start=1)
        ]
        highlighted = [node["id"] for node in safe_nodes]
    else:
        safe_nodes = visible_nodes
        safe_links = visible_links
        safe_preview = [
            {
                "id": record["id"],
                "subject": record.get("subject", ""),
                "date": record.get("date"),
                "sender": record.get("sender"),
                "recipients": match_by_id[record["id"]].get("recipients", []),
                "topic": match_by_id[record["id"]].get("topic", []),
                "snippet": (match_by_id[record["id"]].get("body") or "")[:240],
                "relevance_score": record.get("relevance_score"),
            }
            for record in context
            if record["id"] in match_by_id
        ]
        highlighted = [node["id"] for node in safe_nodes]

    safe_subjects = [record["subject"] for record in safe_preview]
    return {
        "count": len(safe_preview),
        "count_bucket": None,
        "matched_subjects": safe_subjects,
        "highlighted_node_ids": highlighted,
        "relationships_count": len(safe_links),
        "source": retrieved["source"],
        "retrieval_mode": retrieved.get("retrieval_mode", "unknown"),
        "preview": safe_preview,
        "graph": {"nodes": safe_nodes, "links": safe_links},
    }


def sanitize_high_answer(answer: Dict, records_provided: int = 0) -> Dict:
    """Enforce the high-risk output constraints after model generation."""
    answer = dict(answer)
    if records_provided == 0:
        answer["summary"] = (
            "At this disclosure level, specific email records and organizational details are withheld. "
            "No message-level details are disclosed to support a more detailed summary."
        )
        answer["findings"] = [
            "Specific message details are withheld under the privacy policy.",
            "No disclosed records are available to substantiate organizational themes or activities.",
        ]
        answer["confidence"] = 0.20
    else:
        answer["summary"] = _MONEY_RE.sub(
            "[REDACTED_AMOUNT]", redact_text(str(answer.get("summary") or ""))
        )
    answer["findings"] = [
        _MONEY_RE.sub("[REDACTED_AMOUNT]", redact_text(str(finding)))
        for finding in answer.get("findings", [])
    ]
    answer["sources"] = []
    return answer

def sanitize_medium_answer(answer: Dict, records_provided: int = 0) -> Dict:
    """Prevent generated medium-tier answers from reintroducing details or overstating evidence."""
    answer = dict(answer)
    answer["summary"] = _MONEY_RE.sub(
        "[REDACTED_AMOUNT]", redact_text(str(answer.get("summary") or ""))
    )
    if records_provided:
        summary = answer["summary"]
        lower_summary = summary.lower()
        if (
            "not an exhaustive search" not in lower_summary
            or "additional matching records may exist" not in lower_summary
        ):
            summary += (
                f" This answer is based on {records_provided} retrieved sample "
                "record(s), not an exhaustive search; additional matching records may exist."
            )
        answer["summary"] = summary
    for key in ("findings", "sources"):
        values = answer.get(key)
        if isinstance(values, list):
            answer[key] = [
                _MONEY_RE.sub("[REDACTED_AMOUNT]", redact_text(str(value)))
                for value in values
            ]
    return answer
