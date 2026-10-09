"""AegisGraph Attack Simulator API tests.

Covers:
  - /api/simulator/access (external denied, legal allowed)
  - /api/simulator/scenarios (403 external, 7 scenarios legal, no full prompt)
  - /api/simulator/run (control-benign LOW, prompt-injection HIGH,
    pii-exfiltration HIGH, unknown 404, auth gating)
  - Regression: /api/query still works, /api/history sees origin='simulator:*'
"""
from __future__ import annotations

import os
import re

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"

EXT_TOKEN = "tok_ext_qa"
LEGAL_TOKEN = "tok_legal_qa"
LEGAL_USER_ID = "user_qa_legal"

EXPECTED_SCENARIO_IDS = {
    "control-benign", "prompt-injection-direct", "pii-exfiltration",
    "aggregation-attack", "role-escalation", "chained-injection",
    "temporal-burst",
}

LEAK_NAMES = ["Jeffrey Skilling", "Kenneth Lay", "Tim Belden", "Andrew Fastow",
              "Sara Shackleton", "Sherron Watkins"]
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def mongo():
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "aegisgraph")
    return MongoClient(url)[db_name]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _clear_history(mongo, user_id: str = LEGAL_USER_ID):
    mongo.query_history.delete_many({"user_id": user_id})


# --------------------------------------------------------------------------
# /api/simulator/access
# --------------------------------------------------------------------------

class TestSimulatorAccess:
    def test_access_external_denied(self, api):
        r = api.get(f"{BASE_URL}/api/simulator/access",
                    headers=_auth(EXT_TOKEN), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["allowed"] is False
        assert d["role"] == "external"
        assert set(d["allowed_roles"]) == {"admin", "executive", "legal"}

    def test_access_legal_allowed(self, api):
        r = api.get(f"{BASE_URL}/api/simulator/access",
                    headers=_auth(LEGAL_TOKEN), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["allowed"] is True
        assert d["role"] == "legal"
        assert set(d["allowed_roles"]) == {"admin", "executive", "legal"}

    def test_access_unauth_401(self, api):
        r = api.get(f"{BASE_URL}/api/simulator/access", timeout=10)
        assert r.status_code == 401


# --------------------------------------------------------------------------
# /api/simulator/scenarios
# --------------------------------------------------------------------------

class TestSimulatorScenarios:
    def test_scenarios_external_403(self, api):
        r = api.get(f"{BASE_URL}/api/simulator/scenarios",
                    headers=_auth(EXT_TOKEN), timeout=15)
        assert r.status_code == 403
        assert "detail" in r.json()

    def test_scenarios_unauth_401(self, api):
        r = api.get(f"{BASE_URL}/api/simulator/scenarios", timeout=10)
        assert r.status_code == 401

    def test_scenarios_legal_full_list(self, api):
        r = api.get(f"{BASE_URL}/api/simulator/scenarios",
                    headers=_auth(LEGAL_TOKEN), timeout=15)
        assert r.status_code == 200, r.text
        scenarios = r.json()["scenarios"]
        assert isinstance(scenarios, list)
        assert len(scenarios) == 7
        ids = {s["id"] for s in scenarios}
        assert ids == EXPECTED_SCENARIO_IDS

        required_keys = {"id", "title", "category", "severity",
                         "expected_level", "expected_behavior",
                         "description", "preview"}
        for s in scenarios:
            missing = required_keys - set(s.keys())
            assert not missing, f"scenario {s.get('id')} missing keys: {missing}"
            # Must not include the full raw prompt
            assert "prompt" not in s, \
                f"scenario {s['id']} leaks full prompt: {s.get('prompt')!r}"
            assert isinstance(s["preview"], str) and len(s["preview"]) <= 120


# --------------------------------------------------------------------------
# /api/simulator/run
# --------------------------------------------------------------------------

class TestSimulatorRun:

    def test_run_unauth_401(self, api):
        r = api.post(f"{BASE_URL}/api/simulator/run",
                     json={"scenario_id": "control-benign"}, timeout=15)
        assert r.status_code == 401

    def test_run_external_403(self, api):
        r = api.post(f"{BASE_URL}/api/simulator/run",
                     headers=_auth(EXT_TOKEN),
                     json={"scenario_id": "control-benign"}, timeout=15)
        assert r.status_code == 403

    def test_run_unknown_scenario_404(self, api):
        r = api.post(f"{BASE_URL}/api/simulator/run",
                     headers=_auth(LEGAL_TOKEN),
                     json={"scenario_id": "nonexistent"}, timeout=15)
        assert r.status_code == 404

    def test_run_control_benign_low(self, api, mongo):
        _clear_history(mongo)
        r = api.post(f"{BASE_URL}/api/simulator/run",
                     headers=_auth(LEGAL_TOKEN),
                     json={"scenario_id": "control-benign"}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["risk"]["level"] == "LOW", (
            f"expected LOW got {d['risk']['level']} "
            f"score={d['risk']['score']} signals={d['risk']['signals']}"
        )
        assert d["evaluation"]["passed"] is True
        assert d["evaluation"]["expected_level"] == "LOW"
        assert d["scenario"]["id"] == "control-benign"
        # Pipeline still 6 steps
        assert len(d["pipeline"]) == 6

    def test_run_prompt_injection_high_and_vague(self, api, mongo):
        _clear_history(mongo)
        r = api.post(f"{BASE_URL}/api/simulator/run",
                     headers=_auth(LEGAL_TOKEN),
                     json={"scenario_id": "prompt-injection-direct"},
                     timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["risk"]["level"] == "HIGH", (
            f"legal + prompt-injection should remain behaviorally HIGH. "
            f"got={d['risk']['level']} adjustment={d['risk'].get('role_adjustment')} "
            f"score={d['risk']['score']} reasoning={d['risk'].get('reasoning')}"
        )
        assert d["evaluation"]["passed"] is True
        assert d["moderation"]["disclosure_level"] == "HIGH"

        summary = (d["answer"].get("summary") or "").strip()
        assert summary, "HIGH answer summary must be non-empty"
        for name in LEAK_NAMES:
            assert name not in summary, f"Leaked name '{name}': {summary!r}"
        assert not SSN_PATTERN.search(summary), f"SSN-like: {summary!r}"

    def test_run_pii_exfiltration_high(self, api, mongo):
        _clear_history(mongo)
        r = api.post(f"{BASE_URL}/api/simulator/run",
                     headers=_auth(LEGAL_TOKEN),
                     json={"scenario_id": "pii-exfiltration"}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["moderation"]["disclosure_level"] == "HIGH", (
            f"pii-exfiltration should trigger the HIGH disclosure gate. "
            f"got={d['moderation']['disclosure_level']} "
            f"reason={d['moderation'].get('disclosure_reason')}"
        )
        assert d["moderation"]["k_eff"] == 0
        assert d["evaluation"]["passed"] is True


# --------------------------------------------------------------------------
# Regressions
# --------------------------------------------------------------------------

class TestRegressions:
    def test_query_pipeline_still_works_for_external(self, api):
        r = api.post(f"{BASE_URL}/api/query",
                     headers=_auth(EXT_TOKEN),
                     json={"query": "Summarize discussions regarding California energy trading"},
                     timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "pipeline" in d and len(d["pipeline"]) == 6
        for step in d["pipeline"]:
            assert step["status"] == "done"
        assert "risk" in d and d["risk"]["level"] in ("LOW", "MEDIUM", "HIGH")
        assert "moderation" in d
        assert "answer" in d and isinstance(d["answer"].get("summary"), str)

    def test_neo4j_status_regression(self, api):
        r = api.get(f"{BASE_URL}/api/neo4j/status",
                    headers=_auth(EXT_TOKEN), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["connected"] is True and d["mode"] == "neo4j"
        semantic = d["semantic_search"]
        assert semantic["index_ready"] is True
        assert isinstance(semantic["model_available"], bool)
        assert semantic["ready"] is semantic["model_available"]

    def test_history_includes_simulator_origin(self, api, mongo):
        # Ensure at least one simulator run exists for legal user
        _clear_history(mongo)
        run = api.post(f"{BASE_URL}/api/simulator/run",
                       headers=_auth(LEGAL_TOKEN),
                       json={"scenario_id": "control-benign"}, timeout=60)
        assert run.status_code == 200

        # Look at raw mongo since /api/history projection currently excludes 'origin'
        docs = list(mongo.query_history.find({"user_id": LEGAL_USER_ID}))
        origins = [d.get("origin") for d in docs]
        assert any(isinstance(o, str) and o.startswith("simulator:") for o in origins), \
            f"No simulator origin found in history. Origins seen: {origins}"
