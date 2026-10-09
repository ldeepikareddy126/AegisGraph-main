from __future__ import annotations

from aegis.kg_retrieval import Neo4jRetriever


class _Result(list):
    def single(self):
        return self[0] if self else None


class _Session:
    def __init__(self, *, complete=True, matches=True, semantic_error=False):
        self.complete = complete
        self.matches = matches
        self.semantic_error = semantic_error
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def run(self, query, **params):
        self.calls.append((query, params))
        if "RETURN 1 AS connected" in query:
            return _Result([{"connected": 1}])
        if "RETURN node_count, person_count, email_count" in query:
            return _Result([{
                "node_count": 10,
                "person_count": 3,
                "email_count": 7,
            }])
        if "classified_count" in query:
            return _Result([{
                "person_count": 3,
                "classified_count": 3,
                "employee_count": 139,
            }])
        if "SHOW INDEXES" in query:
            return _Result([{
                "type": "VECTOR",
                "state": "ONLINE",
                "labelsOrTypes": ["Email"],
                "properties": ["aegis_embedding"],
                "options": {"indexConfig": {"vector.dimensions": 384}},
            }])
        if "count(e.aegis_embedding)" in query:
            total = 2
            embedded = 2 if self.complete else 1
            return _Result([{
                "total": total,
                "embedded": embedded,
                "current_model": embedded,
            }])
        if "db.index.vector.queryNodes" in query:
            if self.semantic_error:
                raise RuntimeError("Vector index query unavailable")
            assert params["index"] == "aegis_email_embedding"
            assert params["candidate_limit"] >= params["k"]
            assert len(params["embedding"]) == 384
            assert params["minimum_score"] == 0.75
            assert "WHERE score >= $minimum_score" in query
            if not self.matches:
                return _Result()
            return _Result([{
                "s": {"id": "sender@example.test", "name": "Sender"},
                "m": {
                    "email_id": "email-1",
                    "subject": "Weather derivatives",
                    "body": "Discussion of climate-related risk.",
                    "sent_at": "2001-01-01",
                },
                "recipients": [{"id": "recipient@example.test", "name": "Recipient"}],
                "topics": ["weather"],
                "relevance_score": 0.91,
            }])
        if "MATCH (s:Person)-[:SENT]->(m:Email)" in query:
            if not self.matches:
                return _Result()
            return _Result([{
                "s": {"id": "sender@example.test", "name": "Sender"},
                "m": {
                    "email_id": "email-1",
                    "subject": "California market discussion",
                    "body": "Discussion of energy trading and regulatory risk.",
                    "sent_at": "2001-01-01",
                },
                "recipients": [{"id": "recipient@example.test", "name": "Recipient"}],
                "topics": ["energy"],
                "relevance_score": 0.5,
            }])
        raise AssertionError(f"Unexpected Cypher in test: {query}")


class _Driver:
    def __init__(self, *, complete=True, matches=True, semantic_error=False):
        self.complete = complete
        self.matches = matches
        self.semantic_error = semantic_error
        self.sessions = []

    def session(self, **_kwargs):
        session = _Session(
            complete=self.complete,
            matches=self.matches,
            semantic_error=self.semantic_error,
        )
        self.sessions.append(session)
        return session


class _Model:
    def encode(self, _query, **_kwargs):
        return [0.0] * 384


def _retriever(driver):
    retriever = Neo4jRetriever.__new__(Neo4jRetriever)
    retriever._driver = driver
    retriever.database = "aegisgraph"
    retriever._legacy_schema_available = False
    retriever._verification_cache = None
    retriever._verification_checked_at = 0.0
    retriever._semantic_status_cache = None
    retriever._semantic_status_checked_at = 0.0
    return retriever


def test_complete_vector_index_selects_semantically_ranked_emails(monkeypatch):
    monkeypatch.setattr(
        Neo4jRetriever, "_get_semantic_model", staticmethod(lambda: _Model())
    )
    driver = _Driver()

    result = _retriever(driver).retrieve("work relating to climate risk")

    assert result["retrieval_mode"] == "semantic"
    assert result["matched_emails"][0]["subject"] == "Weather derivatives"
    assert result["matched_emails"][0]["relevance_score"] == 0.91
    vector_call = next(
        call for session in driver.sessions for call in session.calls
        if "db.index.vector.queryNodes" in call[0]
    )
    assert vector_call[1]["embedding"] == [0.0] * 384


def test_employee_count_returns_only_classified_graph_aggregate():
    driver = _Driver()
    retriever = _retriever(driver)

    count = retriever.employee_count()

    assert count == 139
    query = driver.sessions[0].calls[0][0]
    assert "p.is_employee = true" in query
    assert "count(DISTINCT" in query
    assert "RETURN p" not in query


def test_graph_verification_caches_counts_but_pings_database():
    retriever = _retriever(_Driver())

    first = retriever.verify()
    second = retriever.verify()

    assert first == {
        "node_count": 10,
        "person_count": 3,
        "email_count": 7,
    }
    assert second == first
    queries = [
        query
        for session in retriever._driver.sessions
        for query, _params in session.calls
    ]
    assert sum("RETURN node_count, person_count, email_count" in query for query in queries) == 1
    assert sum("RETURN 1 AS connected" in query for query in queries) == 1


def test_graph_verification_refresh_recounts_graph():
    retriever = _retriever(_Driver())
    retriever.verify()
    retriever._verification_checked_at = 0.0

    retriever.verify()

    queries = [
        query
        for session in retriever._driver.sessions
        for query, _params in session.calls
    ]
    assert sum("RETURN node_count, person_count, email_count" in query for query in queries) == 2


def test_partial_vector_index_is_not_reported_ready():
    retriever = _retriever(_Driver(complete=False))

    status = retriever.semantic_index_status()

    assert status["ready"] is False
    assert status["embedded_emails"] == 1
    assert status["total_emails"] == 2


def test_complete_vector_index_without_local_model_uses_keyword_fallback(monkeypatch):
    def unavailable_model():
        raise RuntimeError("The semantic embedding model is unavailable.")

    monkeypatch.setattr(
        Neo4jRetriever, "_get_semantic_model", staticmethod(unavailable_model)
    )
    driver = _Driver()

    result = _retriever(driver).retrieve(
        "Summarize California energy trading discussions"
    )

    assert result["retrieval_mode"] == "keyword_fallback"
    assert result["matched_emails"][0]["subject"] == "California market discussion"
    fallback_call = next(
        call for session in driver.sessions for call in session.calls
        if "reduce(score = 0, term IN $terms" in call[0]
    )
    assert fallback_call[1]["terms"] == ["california", "energy", "trading"]


def test_vector_query_failure_degrades_to_keyword_retrieval(monkeypatch):
    monkeypatch.setattr(
        Neo4jRetriever, "_get_semantic_model", staticmethod(lambda: _Model())
    )
    result = _retriever(_Driver(semantic_error=True)).retrieve(
        "California energy trading discussions"
    )

    assert result["retrieval_mode"] == "keyword_fallback"
    assert result["matched_emails"][0]["subject"] == "California market discussion"


def test_semantic_search_rejects_below_threshold_results(monkeypatch):
    monkeypatch.setattr(
        Neo4jRetriever, "_get_semantic_model", staticmethod(lambda: _Model())
    )

    result = _retriever(_Driver(matches=False)).retrieve("an unrelated query")

    assert result["retrieval_mode"] == "semantic"
    assert result["matched_emails"] == []
    assert result["graph"] == {"nodes": [], "links": []}
