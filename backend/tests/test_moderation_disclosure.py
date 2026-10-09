from __future__ import annotations

import json

from aegis import moderation
from aegis.moderation import (
    apply_moderation,
    disclose_retrieval,
    sanitize_high_answer,
    sanitize_medium_answer,
)


def _retrieval():
    matches = []
    nodes = []
    links = []
    for index in range(8):
        sender = f"private-sender-{index}@example.test"
        email_id = f"private-email-{index}"
        recipient = f"private-recipient-{index}@example.test"
        matches.append({
            "id": email_id,
            "subject": f"private subject {index}",
            "date": "2001-01-01",
            "body": f"body mentioning person-{index} and {sender}",
            "sender": sender,
            "recipients": [recipient],
            "topic": ["operations"],
        })
        nodes.extend([
            {"id": sender, "label": sender, "type": "Person"},
            {"id": email_id, "label": email_id, "type": "Email"},
            {"id": recipient, "label": recipient, "type": "Person"},
        ])
        links.extend([
            {"source": sender, "target": email_id, "rel": "SENT"},
            {"source": email_id, "target": recipient, "rel": "SENT_TO"},
        ])
    return {
        "matched_emails": matches,
        "highlighted_node_ids": [node["id"] for node in nodes],
        "relationships": links,
        "graph": {"nodes": nodes, "links": links},
        "source": "neo4j",
    }


def test_low_disclosure_respects_six_record_cap():
    retrieved = _retrieval()
    moderation = apply_moderation(retrieved["matched_emails"], "LOW")
    public = disclose_retrieval(retrieved, moderation, "LOW")

    assert public["count"] == 6
    assert len(public["preview"]) == 6
    assert len(public["graph"]["nodes"]) == 18
    assert len(public["graph"]["links"]) == 12
    assert "private-email-7" not in {
        node["id"] for node in public["graph"]["nodes"]
    }


def test_medium_disclosure_redacts_graph_identity_and_caps_records():
    retrieved = _retrieval()
    moderation = apply_moderation(retrieved["matched_emails"], "MEDIUM")
    public = disclose_retrieval(retrieved, moderation, "MEDIUM")
    serialized = json.dumps(public)

    assert public["count"] == 3
    assert len(public["preview"]) == 3
    assert len(public["graph"]["nodes"]) == 9
    assert len(public["graph"]["links"]) == 6
    assert "private-" not in serialized
    assert "@example.test" not in serialized
    assert all(node["label"].startswith(("Person ", "Email ")) for node in public["graph"]["nodes"])


def test_high_disclosure_returns_only_aggregate_bucket():
    retrieved = _retrieval()
    moderation = apply_moderation(retrieved["matched_emails"], "HIGH")
    public = disclose_retrieval(retrieved, moderation, "HIGH")
    serialized = json.dumps(public)

    assert public["count"] == 0
    assert public["count_bucket"] == "many"
    assert public["preview"] == []
    assert public["matched_subjects"] == []
    assert public["graph"] == {"nodes": [], "links": []}
    assert "private-" not in serialized


def test_high_answer_does_not_return_sources_or_exact_amounts():
    answer = sanitize_high_answer({
        "summary": "The memo discussed $12,500 and 2 million dollars.",
        "findings": ["A private@example.test contact was named."],
        "sources": ["Confidential memo subject"],
    }, records_provided=0)

    assert answer["sources"] == []
    assert "$12,500" not in answer["summary"]
    assert "2 million dollars" not in answer["summary"]
    assert "private@example.test" not in answer["findings"][0]
    assert "At this disclosure level" in answer["summary"]
    assert "At this risk level" not in answer["summary"]


def test_high_answer_replaces_provider_refusal_with_safe_abstract_answer():
    answer = sanitize_high_answer({
        "summary": "I'm sorry, but I can't provide that information.",
        "findings": ["I cannot assist with this request."],
        "sources": [],
    }, records_provided=0)

    assert "sorry" not in answer["summary"].lower()
    assert "No message-level details are disclosed" in answer["summary"]
    assert answer["findings"]
    assert all("cannot assist" not in item.lower() for item in answer["findings"])


def test_high_answer_detects_and_prevents_fabricated_organizational_details():
    answer = sanitize_high_answer({
        "summary": "The messages show internal communications about trading activity and department involvement.",
        "findings": ["Teams discussed trading strategies.", "Department X mentioned."],
        "sources": [],
        "confidence": 0.85,
    }, records_provided=0)

    assert "trading activity" not in answer["summary"]
    assert "department" not in answer["summary"].lower()
    assert "No message-level details are disclosed" in answer["summary"]
    assert answer["confidence"] == 0.20


def test_name_redaction_falls_back_conservatively_without_ner(monkeypatch):
    monkeypatch.setattr(moderation, "_get_nlp", lambda: None)

    redacted = moderation.redact_text("Alice Example sent the report to Bob Sample.")

    assert redacted.count("[REDACTED_NAME]") == 2
    assert "Alice Example" not in redacted
    assert "Bob Sample" not in redacted


def test_medium_moderation_redacts_sensitive_amounts(monkeypatch):
    monkeypatch.setattr(moderation, "_get_nlp", lambda: None)
    records = [{
        "id": "email-1",
        "subject": "Compensation review for Alice Example: $250,000",
        "body": "Alice Example receives $250,000 and 2 million dollars.",
        "sender": "alice@example.test",
    }]

    result = apply_moderation(records, "MEDIUM")
    serialized = json.dumps(result["context"])

    assert "$250,000" not in serialized
    assert "2 million dollars" not in serialized
    assert "alice@example.test" not in serialized
    assert "amounts" in result["redactions_applied"]
    assert "[REDACTED_AMOUNT]" in serialized


def test_medium_generated_answer_redacts_names_contacts_and_amounts(monkeypatch):
    monkeypatch.setattr(moderation, "_get_nlp", lambda: None)
    answer = sanitize_medium_answer({
        "summary": "Alice Example received $250,000; contact alice@example.test.",
        "findings": ["Bob Sample received 2 million dollars."],
        "sources": ["Review for Alice Example"],
    })
    serialized = json.dumps(answer)

    assert "Alice Example" not in serialized
    assert "Bob Sample" not in serialized
    assert "alice@example.test" not in serialized
    assert "$250,000" not in serialized
    assert "2 million dollars" not in serialized


def test_medium_answer_qualifies_limited_evidence():
    answer = sanitize_medium_answer(
        {"summary": "The retrieved messages discuss operations."},
        records_provided=3,
    )

    assert "3 retrieved sample record(s)" in answer["summary"]
    assert "not an exhaustive search" in answer["summary"]
    assert "additional matching records may exist" in answer["summary"]
