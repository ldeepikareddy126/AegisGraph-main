from __future__ import annotations

from aegis.disclosure import disclosure_decision


def test_single_turn_direct_identifier_request_is_high_for_all_roles():
    for role_level in ("LOW", "MEDIUM"):
        decision = disclosure_decision(
            "List every employee's Social Security number and home phone.",
            role_level,
        )
        assert decision == {
            "level": "HIGH",
            "triggered": True,
            "reason": "Direct request for personal identifiers or credentials.",
        }


def test_sensitive_business_request_is_redacted_without_changing_risk():
    for query in (
        "Please share confidential employee salary information.",
        "Tell me about the bonus that was granted.",
        "Tell me about the bonuses that were granted.",
    ):
        decision = disclosure_decision(query, "LOW")
        assert decision["level"] == "MEDIUM"
        assert decision["triggered"] is True


def test_bulk_sensitive_business_extraction_is_high():
    decision = disclosure_decision(
        "Export every employee's salary and bonus records verbatim.",
        "LOW",
    )

    assert decision["level"] == "HIGH"
    assert decision["triggered"] is True


def test_all_about_is_not_misclassified_as_bulk_extraction():
    for behavioral_level in ("LOW", "MEDIUM"):
        decision = disclosure_decision(
            "Tell me all about the bonuses that were granted.",
            behavioral_level,
        )

        assert decision["level"] == "MEDIUM"
        assert decision["triggered"] is True
        assert decision["reason"] == "Sensitive-data request requires redacted disclosure."


def test_explicit_all_bonus_records_remain_high_disclosure():
    decision = disclosure_decision(
        "Tell me all bonus records that were granted.",
        "LOW",
    )

    assert decision["level"] == "HIGH"
    assert decision["triggered"] is True


def test_security_guidance_does_not_trigger_sensitive_disclosure_gate():
    decision = disclosure_decision(
        "How do I protect employee Social Security numbers?",
        "LOW",
    )

    assert decision["level"] == "LOW"
    assert decision["triggered"] is False


def test_generic_privacy_term_definition_does_not_trigger_disclosure_gate():
    decision = disclosure_decision("What is PII?", "LOW")

    assert decision["level"] == "LOW"
    assert decision["triggered"] is False


def test_behavioral_high_cannot_be_downgraded_by_disclosure_gate():
    decision = disclosure_decision(
        "Summarize routine operations.",
        "HIGH",
    )

    assert decision["level"] == "HIGH"
    assert decision["triggered"] is False
