from __future__ import annotations

import asyncio

from aegis import llm


def test_offline_response_identifies_deterministic_fallback(monkeypatch):
    monkeypatch.setattr(llm, "_get_api_config", lambda: (None, "https://api.openai.com/v1"))

    answer = asyncio.run(llm.generate_answer(
        query="What was discussed?",
        moderated_context=[],
        risk_level="LOW",
        moderation_explanation="",
    ))

    assert answer["provider"] == "local-deterministic"
    assert answer["model"] == "aegisgraph-offline"
    assert answer["fallback"] is True
    assert answer["fallback_reason"] == "not_configured"


def test_offline_medium_response_qualifies_retrieved_records():
    answer = llm._mock_answer(
        query="What was discussed?",
        moderated_context=[{
            "subject": "Redacted subject",
            "snippet": "Redacted message",
            "topic": ["operations"],
            "redacted": True,
        }],
        risk_level="MEDIUM",
        topic_hint=None,
    )

    assert "retrieved sample communication record(s)" in answer["summary"]
    assert "not an exhaustive corpus-wide search" in answer["summary"]
    assert "additional matching records may exist" in answer["summary"]


def test_offline_high_response_does_not_infer_from_topic_hints():
    answer = llm._mock_answer(
        query="What was discussed?",
        moderated_context=[],
        risk_level="HIGH",
        topic_hint={
            "topics": ["trading"],
            "departments": ["Finance"],
            "record_count_bucket": "many",
        },
    )

    assert "No message-level details are disclosed" in answer["summary"]
    assert "trading" not in answer["summary"].lower()
    assert "finance" not in answer["summary"].lower()
    assert answer["sources"] == []


def test_successful_response_identifies_configured_llm(monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "choices": [{
                    "message": {
                        "content": '{"summary":"Generated answer","findings":[]}'
                    }
                }]
            }

    class Client:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(
        llm, "_get_api_config",
        lambda: ("test-key", "https://api.example.test/v1"),
    )
    monkeypatch.setattr(llm, "_get_candidate_models", lambda _base_url: ["test-model"])
    monkeypatch.setattr(llm.httpx, "AsyncClient", Client)

    answer = asyncio.run(llm.generate_answer(
        query="What was discussed?",
        moderated_context=[],
        risk_level="LOW",
        moderation_explanation="",
    ))

    assert answer["provider"] == "api.example.test"
    assert answer["model"] == "test-model"
    assert answer["fallback"] is False
