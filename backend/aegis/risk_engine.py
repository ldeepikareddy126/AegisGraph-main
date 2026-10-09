"""AegisGraph risk engine.

Implements a lightweight, transparent four-signal behavioral risk score:

    S_sem   – semantic persistence across the active session
    S_temp  – temporal burst rate for the same session
    S_ent   – count of distinct sensitive entities detected
    S_graph – expected retrieval breadth / hop depth

Signals use fixed interpretable weights, receive a small corroboration boost,
are smoothed via EWMA, and then receive role-aware monitoring bias. RBAC and
authorization remain separate from this behavioral score.
"""
from __future__ import annotations

import math
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# Optional real NLP backends (sentence-transformers embeddings + spaCy NER).
# Both are lazily loaded singletons that degrade gracefully to the lexical/
# regex heuristics below if the package isn't installed, the model hasn't
# been downloaded, or loading fails for any other reason — mirroring the
# same fallback philosophy already used for the LLM and Neo4j retrieval.
# --------------------------------------------------------------------------

_EMBED_STATE: Optional[Any] = None
_EMBED_FAILED = False
_EMBED_ERROR: Optional[str] = None
log = logging.getLogger("aegis.risk")

_NLP: Optional[Any] = None
_NLP_FAILED = False


def _get_embedder() -> Optional[Any]:
    global _EMBED_STATE, _EMBED_FAILED, _EMBED_ERROR
    if _EMBED_FAILED or os.environ.get("AEGIS_DISABLE_EMBEDDINGS") == "1":
        return None
    if _EMBED_STATE is None:
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.environ.get("AEGIS_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            model = SentenceTransformer(
                model_name, model_kwargs={"local_files_only": True}
            )
            model.max_seq_length = int(
                os.environ.get("AEGIS_EMBEDDING_MAX_TOKENS", "128")
            )
            _EMBED_STATE = model
        except Exception as ex:
            _EMBED_FAILED = True
            _EMBED_ERROR = f"{type(ex).__name__}: {ex}"
            log.warning(
                "Local semantic embedding model %s could not be loaded; "
                "semantic scoring will use lexical similarity: %s",
                os.environ.get("AEGIS_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
                _EMBED_ERROR,
            )
            return None
    return _EMBED_STATE


def _get_nlp() -> Optional[Any]:
    global _NLP, _NLP_FAILED
    if _NLP_FAILED or os.environ.get("AEGIS_DISABLE_NER") == "1":
        return None
    if _NLP is None:
        try:
            import spacy
            model_name = os.environ.get("AEGIS_SPACY_MODEL", "en_core_web_sm")
            _NLP = spacy.load(model_name, disable=["parser", "lemmatizer"])
        except Exception:
            _NLP_FAILED = True
            return None
    return _NLP

HIGH_CONFIDENCE_INJECTION_PATTERNS = [
    re.compile(r"\b(ignore|disregard|override)\b.{0,40}\b(previous|above|system|developer)\b", re.I),
    re.compile(r"\b(system prompt|developer message)\b.{0,60}\b(reveal|dump|print|verbatim)\b", re.I),
    re.compile(r"\b(raw|verbatim|dump|reveal)\b.{0,60}\b(all|every|full|confidential|private)\b", re.I),
]

ROLE_IMPERSONATION_PATTERNS = [
    re.compile(r"\b(you are now|i am|act as)\b.{0,40}\b(administrator|admin|developer|system)\b", re.I),
    re.compile(r"\b(full|unrestricted)\s+(clearance|access)\b", re.I),
]

SENSITIVE_TERMS = [
    "confidential", "secret", "restricted", "private", "internal",
    "salary", "compensation", "bonus", "severance", "raise",
    "ssn", "social security", "password", "credentials",
    "personal", "phone", "address", "home",
    "trade secret", "insider", "off-balance-sheet", "spe", "ljm",
    "restatement", "fraud", "investigation", "subpoena", "ferc",
    "raptor", "chewco", "sherron watkins",
    "list all", "every email", "everything about", "dump", "export",
    "leak", "reveal", "expose", "bypass",
    "ignore previous", "ignore all previous", "disregard the above",
    "system prompt", "you are now", "act as",
]

PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                                # SSN
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),                    # US phone
    re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),        # email
]

# --------------------------------------------------------------------------
# Role → risk adjustment.  Attached to the user when they log in / set role.
# --------------------------------------------------------------------------
ROLE_PROFILES: Dict[str, Dict[str, float]] = {
    "external":  {"clearance": 0, "bump":  0.15, "label": "External user"},
    "employee":  {"clearance": 1, "bump":  0.00, "label": "Employee"},
    "executive": {"clearance": 3, "bump":  0.05, "label": "Executive"},
    "legal":     {"clearance": 4, "bump":  0.05, "label": "Legal"},
    "admin":     {"clearance": 5, "bump":  0.00, "label": "Administrator"},
}


def detect_entities(text: str) -> List[str]:
    # Structured PII (SSNs, phone numbers, emails) is genuinely better matched
    # by regex than by a general-purpose NER model, so this always runs.
    entities: List[str] = []
    for pat in PII_PATTERNS:
        entities.extend(pat.findall(text))

    nlp = _get_nlp()
    if nlp is not None:
        doc = nlp(text)
        for ent in doc.ents:
            if ent.label_ in {"PERSON", "ORG", "GPE"}:
                entities.append(ent.text)
    else:
        # Fallback heuristic when spaCy isn't installed/loaded: capitalised
        # bigrams are a reasonable proxy for full names.
        for m in re.finditer(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b", text):
            entities.append(m.group(1))
    return entities


def _sensitive_terms(query: str) -> List[str]:
    q = query.lower()
    return [term for term in SENSITIVE_TERMS if term in q]


def _lexical_similarity(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"\w+", left.lower()))
    right_tokens = set(re.findall(r"\w+", right.lower()))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / math.sqrt(len(left_tokens) * len(right_tokens))


def _semantic_persistence(query: str, previous_queries: List[str]) -> float:
    """Return a neutral score for new sessions and [0, 1] persistence otherwise."""
    history = [item for item in previous_queries[-5:] if item]
    if not history:
        return 0.0
    embedder = _get_embedder()
    if embedder is not None:
        vectors = embedder.encode([query] + history, normalize_embeddings=True)
        raw = sum(float(vectors[0] @ vectors[i]) for i in range(1, len(vectors))) / len(history)
        return max(0.0, min(1.0, (raw + 1.0) / 2.0))
    raw = sum(_lexical_similarity(query, old) for old in history) / len(history)
    return max(0.0, min(1.0, raw))


def _temporal_score(
    recent_query_times: List[float],
    request_time: Optional[float] = None,
    recent_query_count: Optional[int] = None,
) -> float:
    if recent_query_count is not None:
        count = max(0, recent_query_count)
    else:
        now = request_time if request_time is not None else time.time()
        count = sum(1 for timestamp in recent_query_times
                    if 0 <= now - timestamp <= 60)
    return math.tanh((count + 1) / 6.0)


def _entity_score(entities: List[str]) -> float:
    counts: Dict[str, int] = {}
    for entity in entities:
        key = entity.strip().lower()
        if key:
            counts[key] = counts.get(key, 0) + 1
    if len(counts) < 2:
        return 0.0
    total = sum(counts.values())
    entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
    concentration = 1.0 - entropy / math.log(len(counts))
    persistence = min(1.0, total / 4.0)
    return max(0.0, min(1.0, concentration * persistence))


def _graph_score(retrieved_emails: int, hop_depth: int) -> float:
    # Saturating: a typical retrieval sits ~0.35, only unusually broad
    # multi-hop expansions push above 0.7.
    return math.tanh((retrieved_emails / 12.0) + (hop_depth / 8.0))


def compute_risk(
    query: str,
    recent_query_times: List[float],
    retrieved_emails: int,
    hop_depth: int,
    prev_ewma: float | None,
    user_role: str = "external",
    ewma_gamma: float = 0.55,
    session_queries: Optional[List[str]] = None,
    session_entities: Optional[List[str]] = None,
    recent_query_count: Optional[int] = None,
    request_time: Optional[float] = None,
) -> Dict[str, Any]:
    session_queries = session_queries or []
    entities = detect_entities(query)
    if session_entities is None:
        session_entities = [
            entity
            for text in session_queries
            for entity in detect_entities(text)
        ]
    all_session_entities = session_entities + entities
    s_sem = _semantic_persistence(query, session_queries)
    sem_hits = _sensitive_terms(query)
    s_temp = _temporal_score(
        recent_query_times,
        request_time=request_time,
        recent_query_count=recent_query_count,
    )
    s_ent = _entity_score(all_session_entities)
    s_graph = _graph_score(retrieved_emails, hop_depth)

    signals = {"semantic": s_sem, "temporal": s_temp,
               "entity": s_ent, "graph": s_graph}

    weights = {"semantic": 0.30, "temporal": 0.20,
               "entity": 0.25, "graph": 0.25}
    composite = sum(weights[k] * signals[k] for k in signals)
    signal_values = list(signals.values())
    corroboration = max(
        (min(signal_values[i], signal_values[j])
         for i in range(len(signal_values))
         for j in range(i + 1, len(signal_values))),
        default=0.0,
    )
    fused = min(1.0, composite + 0.10 * corroboration)
    ewma = ewma_gamma * fused + (1 - ewma_gamma) * (prev_ewma or 0.0)

    profile = ROLE_PROFILES.get(user_role, ROLE_PROFILES["external"])
    injection_hits = [
        pattern.pattern for pattern in HIGH_CONFIDENCE_INJECTION_PATTERNS
        if pattern.search(query)
    ]
    impersonation_hits = [
        pattern.pattern for pattern in ROLE_IMPERSONATION_PATTERNS
        if pattern.search(query)
    ]
    lower_q = query.lower()
    sensitive_query = any(term in lower_q for term in (
        "ssn", "social security", "salary", "phone", "address",
        "email", "personal", "password", "credentials",
    ))
    enumeration = bool(re.search(r"\b(list|every|all|each|dump|export)\b", query, re.I))
    repeated_enumeration = (
        sensitive_query and enumeration and
        sum(
            1 for old in session_queries
            if any(term in old.lower() for term in (
                "ssn", "social security", "salary", "phone", "address",
                "email", "personal", "password", "credentials",
            ))
            and bool(re.search(r"\b(list|every|all|each|dump|export)\b", old, re.I))
        ) >= 1
    )
    hard_gate = 0.0
    hard_gate_reason = ""
    if injection_hits:
        hard_gate = 0.65
        hard_gate_reason = "high-confidence prompt-injection pattern"
    elif impersonation_hits:
        hard_gate = 0.65
        hard_gate_reason = "role-impersonation or security-control bypass pattern"
    elif repeated_enumeration:
        hard_gate = 0.35
        hard_gate_reason = "repeated sensitive enumeration pattern"

    role_adjusted = max(0.0, min(1.0, ewma + profile["bump"]))
    adjusted = max(role_adjusted, hard_gate)

    if adjusted < 0.35:
        level = "LOW"
    elif adjusted < 0.65:
        level = "MEDIUM"
    else:
        level = "HIGH"

    reasoning: List[str] = []
    if sem_hits:
        reasoning.append(f"detected {len(sem_hits)} sensitive term(s): "
                         f"{', '.join(sem_hits[:4])}")
    if s_temp > 0.3:
        reasoning.append("elevated query rate in this session")
    if entities:
        reasoning.append(f"{len(set(entities))} entity/PII mention(s) in the current query")
    if s_graph > 0.55:
        reasoning.append("retrieval spans a wide sub-graph")
    if profile["bump"] > 0:
        reasoning.append(f"user role '{profile['label']}' adds +"
                         f"{profile['bump']:.2f} risk")
    if hard_gate_reason:
        reasoning.append(f"hard gate: {hard_gate_reason}")
    if not reasoning:
        reasoning.append("no strong sensitivity signals detected")

    return {
        "signals":         {k: round(v, 3) for k, v in signals.items()},
        "weights":         weights,
        "composite":       round(composite, 3),
        "corroboration":   round(corroboration, 3),
        "fused":           round(fused, 3),
        "ewma":            round(ewma, 3),
        "role_adjusted":   round(role_adjusted, 3),
        "hard_gate":       round(hard_gate, 3),
        "hard_gate_reason": hard_gate_reason,
        "adjusted":        round(adjusted, 3),
        "level":           level,
        "reasoning":       "; ".join(reasoning),
        "sensitive_terms": sem_hits,
        "entities":        list(set(entities)),
        "role":            user_role,
        "role_label":      profile["label"],
        "role_adjustment": profile["bump"],
    }
