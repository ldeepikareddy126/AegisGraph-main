from __future__ import annotations

import pytest

from aegis.safe_aggregates import (
    append_employee_aggregate,
    requests_employee_aggregate,
)


@pytest.mark.parametrize("query", [
    "How many employees are marked in the graph?",
    "What is the number of employees?",
    "Give me a list of all employees",
    "Show the workforce directory",
])
def test_employee_count_and_full_roster_requests_are_detected(query):
    assert requests_employee_aggregate(query)


@pytest.mark.parametrize("query", [
    "What did employees discuss about market risk?",
    "What is the policy for all employees?",
    "How many emails did the employee send?",
])
def test_unrelated_employee_queries_do_not_trigger_aggregates(query):
    assert not requests_employee_aggregate(query)


def test_medium_answer_gets_qualified_employee_count_without_names():
    answer = append_employee_aggregate(
        {"summary": "Individual names cannot be provided."}, 139, "MEDIUM"
    )

    assert "139 distinct employee records" in answer["summary"]
    assert "not a verified current workforce roster" in answer["summary"]
    assert "Individual names are withheld" in answer["summary"]


def test_existing_model_count_is_canonicalized_without_repeating_it():
    answer = append_employee_aggregate(
        {"summary": "The results indicate 5 distinct employee entries."},
        139,
        "MEDIUM",
    )

    assert answer["summary"].count("139 distinct employee records") == 1
    assert "5 distinct employee entries" not in answer["summary"]
    assert "dataset count" in answer["summary"]


def test_high_answer_never_gets_exact_employee_count():
    answer = {"summary": "Only broad themes are available."}

    assert append_employee_aggregate(answer, 139, "HIGH") is answer
    assert "139" not in answer["summary"]


def test_employee_aggregate_rejects_invalid_negative_count():
    with pytest.raises(ValueError, match="cannot be negative"):
        append_employee_aggregate({"summary": ""}, -1, "MEDIUM")
