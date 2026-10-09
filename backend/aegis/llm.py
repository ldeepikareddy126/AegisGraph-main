"""LLM wrapper. Uses OpenAI/Groq API with an intelligent fallback chain
and deterministic offline fallback so requests always succeed."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

log = logging.getLogger("aegis.llm")

# ChatGPT-style persona and instructions
SYSTEM_PROMPT = """You are AegisGraph, an articulate, highly knowledgeable enterprise AI research assistant built directly on the Enron email knowledge graph.
You communicate with the natural conversational fluency, deep analytical reasoning, and thoroughness of ChatGPT.

Guidelines:
- Tone: Professional, intelligent, articulate, objective, and comprehensive. Provide thoughtful analysis rather than terse, mechanical summaries.
- Grounding: Synthesize facts and narrative context directly from the provided moderated email records. Explain corporate developments, timeline sequences, and business implications clearly.
- Citations: Cite sources by their subject line or discussion topic naturally in your answer. Do not use internal node IDs or database syntax.
- Format: Always reply in EXACT valid JSON (no markdown fences, no surrounding commentary):
  {
    "summary": "Cohesive, articulate, multi-paragraph or well-structured explanation in the style of ChatGPT answering the user's question directly.",
    "findings": ["Insightful finding 1 detailing key actions, numbers, or dates", "Insightful finding 2...", ...],
    "confidence": 0.85,
    "sources": ["Subject 1", "Subject 2"]
  }

Response Mode by Disclosure Tier:
- LOW: Deliver a detailed, expansive, and highly informative answer grounded in the context. Provide clear historical and operational background.
- MEDIUM: Provide a thorough response based on available sample records (typically up to 3 examples). Explicitly note that findings are drawn from limited retrieved records and additional matching records may exist. Acknowledge that personal identifiers (e.g., individual names or direct email addresses) were redacted by the privacy layer. Do not claim findings represent the complete corpus.
- HIGH: Do not output an error message. If no specific records were provided (empty context), respond with ONLY a generic, safe statement that details are withheld. Do not assert that a topic exists unless this is explicitly supported by a supplied topic hint. Do NOT invent organizational themes, department names, or specific activities. If topic hints are provided, use them only to confirm the general domain, not to fabricate details. Do not disclose specific individuals, exact amounts, or internal email subjects.
"""


def _get_api_config() -> Tuple[Optional[str], str]:
    """Inspect environment (without modifying it) to determine API key and base URL."""
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    if not base_url:
        if api_key and api_key.startswith("gsk_"):
            base_url = "https://api.groq.com/openai/v1"
        else:
            base_url = "https://api.openai.com/v1"
    return api_key, base_url.rstrip("/")


def _get_candidate_models(base_url: str) -> List[str]:
    """Build prioritized model candidate list, trying user's configured model first."""
    env_model = os.environ.get("OPENAI_MODEL")
    candidates: List[str] = []
    if env_model:
        candidates.append(env_model.strip())

    if "groq.com" in base_url:
        groq_defaults = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "llama-3.3-70b-versatile"]
        for m in groq_defaults:
            if m not in candidates:
                candidates.append(m)
    else:
        openai_defaults = ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"]
        for m in openai_defaults:
            if m not in candidates:
                candidates.append(m)
    return candidates


# --------------------------------------------------------------------------
# Deterministic offline fallback
# --------------------------------------------------------------------------

def _mock_answer(query: str,
                 moderated_context: List[Dict],
                 risk_level: str,
                 topic_hint: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if risk_level == "HIGH":
        return {
            "summary": (
                "At this disclosure level, specific email records and organizational details are withheld. "
                "No message-level details are disclosed to support a more detailed summary."
            ),
            "findings": [
                "Specific message details are withheld under the privacy policy.",
                "No disclosed records are available to substantiate organizational themes or activities.",
            ],
            "confidence": 0.20,
            "sources": [],
        }

    if not moderated_context:
        return {
            "summary": (
                f"No direct records were identified in the knowledge graph matching "
                f"'{query.strip()}'. You may want to broaden your search terms."
            ),
            "findings": [],
            "confidence": 0.30,
            "sources": [],
        }

    topics = sorted({t for c in moderated_context for t in (c.get("topic") or [])})[:5]
    findings = []
    for c in moderated_context[:4]:
        prefix = "" if not c.get("redacted") else "[Redacted] "
        subj = c.get("subject", "Internal Communication")
        date_str = f" ({c['date']})" if c.get("date") else ""
        snippet = (c.get("snippet") or "")[:180].replace("\n", " ")
        findings.append(f"{prefix}'{subj}'{date_str} – {snippet}")

    topic_str = f" focuses on {', '.join(topics)}." if topics else " spans operational discussions across the organization."
    summary = (
        f"Based on {len(moderated_context)} retrieved sample communication record(s), "
        f"the discussion regarding '{query.strip()}'{topic_str}"
    )
    if risk_level == "MEDIUM":
        summary += (
            " This is a limited sample, not an exhaustive corpus-wide search; "
            "additional matching records may exist. Specific personal names and direct "
            "contact details have been sanitized in accordance with role clearance policies."
        )

    return {
        "summary": summary,
        "findings": findings,
        "confidence": 0.82 if risk_level == "LOW" else 0.65,
        "sources": [c["subject"] for c in moderated_context if c.get("subject")],
    }


def _offline_answer(
    query: str,
    moderated_context: List[Dict],
    risk_level: str,
    topic_hint: Optional[Dict[str, Any]],
    reason: str,
) -> Dict[str, Any]:
    answer = _mock_answer(query, moderated_context, risk_level, topic_hint)
    answer.update({
        "provider": "local-deterministic",
        "model": "aegisgraph-offline",
        "fallback": True,
        "fallback_reason": reason,
    })
    return answer


# --------------------------------------------------------------------------
# Live LLM Generation (ChatGPT-style)
# --------------------------------------------------------------------------

async def generate_answer(
    query: str,
    moderated_context: List[Dict],
    risk_level: str,
    moderation_explanation: str,
    topic_hint: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    safe_facts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    api_key, base_url = _get_api_config()
    if not api_key:
        log.info("No API key configured; using deterministic response.")
        return _offline_answer(
            query, moderated_context, risk_level, topic_hint, "not_configured"
        )

    if risk_level == "HIGH":
        ctx_block = (
            "(Privacy policy: No specific email context released – only high-level topic hints are available.\n"
            "Do NOT invent organizational details, department names, or specific activities based on these hints.\n"
            "If no records were provided, respond with a safe, generic statement only.)\n"
            f"TOPIC HINT: {json.dumps(topic_hint or {}, ensure_ascii=False)}"
        )
    elif not moderated_context:
        ctx_block = "(No matching email records found in the knowledge graph.)"
    else:
        record_note = (
            f"(These {len(moderated_context)} record(s) are sampled from retrieved "
            "results. Additional matching records may exist.)"
            if risk_level == "MEDIUM"
            else ""
        )
        ctx_lines = [record_note] if record_note else []
        for i, c in enumerate(moderated_context, 1):
            sender = c.get("sender") or "Unknown"
            dept = f" ({c.get('sender_department')})" if c.get("sender_department") else ""
            date_str = f" | Date: {c.get('date')}" if c.get("date") else ""
            ctx_lines.append(
                f"[{i}] Subject: {c.get('subject', 'No Subject')}{date_str} | "
                f"From: {sender}{dept}\n"
                f"Snippet: {c.get('snippet', '')[:1000]}"
            )
        ctx_block = "\n\n".join(ctx_lines)

    safe_fact_block = (
        "\n".join(f"- {fact}" for fact in safe_facts)
        if safe_facts
        else "No separate aggregate facts are available. Do not infer corpus-wide totals from sampled records."
    )
    evidence_note = ""
    if risk_level == "MEDIUM" and moderated_context:
        evidence_note = (
            f"\n\nIMPORTANT: The {len(moderated_context)} records shown are examples "
            "from a limited retrieval. Explicitly note in your answer that findings "
            "are based on available sample records and the full scope may be larger."
        )
    elif risk_level == "HIGH" and not moderated_context:
        evidence_note = (
            "\n\nIMPORTANT: No specific records were provided for HIGH tier. Do NOT "
            "fabricate organizational details, activities, or department involvement. "
            "Respond with a safe, generic statement only."
        )

    user_prompt = (
        f"USER QUESTION:\n{query}\n\n"
        f"DISCLOSURE TIER: {risk_level}\n"
        f"MODERATION DIRECTIVE: {moderation_explanation}\n\n"
        f"MODERATED EMAIL CONTEXT:\n{ctx_block}\n\n"
        f"VERIFIED NON-IDENTIFYING AGGREGATE FACTS:\n{safe_fact_block}\n\n"
        "Treat aggregate facts as authoritative and do not infer totals from "
        "the limited email context."
        f"{evidence_note}\n\n"
        "Provide a comprehensive, conversational, ChatGPT-style answer. "
        "Return ONLY the requested JSON object without markdown fences."
    )

    models_to_try = _get_candidate_models(base_url)
    timeout = httpx.Timeout(25.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in models_to_try:
            try:
                log.info(f"Calling LLM at {base_url} with model {model}...")
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.4,
                        "max_tokens": 1200,
                        "response_format": {"type": "json_object"},
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    m = re.search(r"\{.*\}", content, re.DOTALL)
                    if m:
                        parsed = json.loads(m.group(0))
                        parsed.setdefault("summary", "")
                        parsed.setdefault("findings", [])
                        parsed.setdefault("confidence", 0.88)
                        parsed.setdefault("sources", [])
                        parsed.update({
                            "provider": urlparse(base_url).netloc,
                            "model": model,
                            "fallback": False,
                        })
                        log.info(f"Successfully generated response via {model}")
                        return parsed
                elif resp.status_code in (400, 404):
                    log.warning(f"Model {model} returned HTTP {resp.status_code} ({resp.text[:150]}); trying next model...")
                    continue
                else:
                    log.error(f"LLM API returned unexpected status {resp.status_code}: {resp.text[:200]}")
            except Exception as ex:
                log.warning(f"Failed to query model {model}: {ex}")
                continue

    log.warning("All LLM attempts exhausted; falling back to offline answer.")
    return _offline_answer(
        query, moderated_context, risk_level, topic_hint, "provider_unavailable"
    )
