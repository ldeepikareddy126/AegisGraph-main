"""Neo4j-only retrieval for the Enron Knowledge Graph.

Semantic vector retrieval is preferred when its index is ready. Literal
compatibility paths support an unindexed graph and the older Employee schema;
there is no in-memory or demo-corpus retrieval fallback.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("aegis.retrieval")

SEMANTIC_INDEX_NAME = "aegis_email_embedding"
SEMANTIC_VECTOR_PROPERTY = "aegis_embedding"
GRAPH_VERIFICATION_CACHE_SECONDS = 60


def semantic_model_name() -> str:
    return os.environ.get("AEGIS_EMBEDDING_MODEL", "all-MiniLM-L6-v2")


def semantic_model_revision() -> str:
    token_limit = os.environ.get("AEGIS_EMBEDDING_MAX_TOKENS", "128")
    return f"{semantic_model_name()}:tokens={token_limit}"


def semantic_min_score() -> float:
    score = float(os.environ.get("AEGIS_SEMANTIC_MIN_SCORE", "0.75"))
    if not -1.0 <= score <= 1.0:
        raise ValueError("AEGIS_SEMANTIC_MIN_SCORE must be between -1 and 1.")
    return score


_QUERY_STOPWORDS = {
    "about", "after", "also", "among", "and", "are", "before", "between",
    "could", "describe", "discuss", "discussed", "discussions", "does",
    "during", "enron",
    "every", "find", "from", "give", "have", "into", "list", "more", "please",
    "show", "some", "summarise", "summarize", "that", "the", "their", "them",
    "there", "these", "they",
    "this", "those", "through", "what", "when", "where", "which", "while",
    "with", "would",
}


def _query_terms(query: str) -> List[str]:
    """Extract a bounded, stable set of useful terms for offline lexical retrieval."""
    terms = []
    seen = set()
    for term in re.findall(r"[a-z0-9]{3,}", query.lower()):
        if term not in _QUERY_STOPWORDS and term not in seen:
            seen.add(term)
            terms.append(term)
        if len(terms) == 12:
            break
    return terms


class Neo4jUnavailableError(RuntimeError):
    """Raised when the configured Neo4j database cannot be queried."""


class Neo4jRetriever:
    """Read-only wrapper around Neo4j driver matching Enron Knowledge Graph schema."""

    def __init__(self, uri: str, user: str, password: str,
                 database: Optional[str] = None):
        from neo4j import GraphDatabase
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database
        self.database = database
        self._legacy_schema_available: Optional[bool] = None
        self._verification_cache: Optional[Dict[str, int]] = None
        self._verification_checked_at = 0.0
        self._semantic_status_cache: Optional[Dict[str, Any]] = None
        self._semantic_status_checked_at = 0.0

    def close(self):
        try:
            self._driver.close()
        except Exception:
            pass

    def verify(self) -> Dict[str, Any]:
        session_kwargs = {"database": self.database} if self.database else {}
        with self._driver.session(**session_kwargs) as s:
            now = time.monotonic()
            if (
                self._verification_cache is not None
                and now - self._verification_checked_at
                < GRAPH_VERIFICATION_CACHE_SECONDS
            ):
                record = s.run("RETURN 1 AS connected").single()
                if not record or record["connected"] != 1:
                    raise Neo4jUnavailableError(
                        "Neo4j connectivity check did not return a healthy result."
                    )
                return dict(self._verification_cache)

            result = s.run("""
                CALL () { MATCH (n) RETURN count(n) AS node_count }
                CALL () { MATCH (p:Person) RETURN count(p) AS person_count }
                CALL () { MATCH (m:Email) RETURN count(m) AS email_count }
                RETURN node_count, person_count, email_count
            """)
            record = result.single()
        verification = {
            "node_count": int(record["node_count"]) if record else 0,
            "person_count": int(record["person_count"]) if record else 0,
            "email_count": int(record["email_count"]) if record else 0,
        }
        self._verification_cache = verification
        self._verification_checked_at = time.monotonic()
        return dict(verification)

    def employee_count(self) -> int:
        """Count graph records explicitly classified as employees, without returning identities."""
        session_kwargs = {"database": self.database} if self.database else {}
        with self._driver.session(**session_kwargs) as session:
            record = session.run("""
                MATCH (p:Person)
                RETURN count(p) AS person_count,
                       count(p.is_employee) AS classified_count,
                       count(DISTINCT CASE WHEN p.is_employee = true
                                           THEN p.email END) AS employee_count
            """).single()

        if not record or int(record["classified_count"]) == 0:
            raise Neo4jUnavailableError(
                "The configured graph does not contain classified employee records."
            )
        return int(record["employee_count"])

    def semantic_index_status(self, refresh: bool = False) -> Dict[str, Any]:
        """Report vector-index readiness separately from local model readiness."""
        if (
            not refresh
            and self._semantic_status_cache is not None
            and time.monotonic() - self._semantic_status_checked_at < 60
        ):
            return dict(self._semantic_status_cache)

        session_kwargs = {"database": self.database} if self.database else {}
        with self._driver.session(**session_kwargs) as session:
            indexes = list(session.run("""
                SHOW INDEXES
                YIELD name, type, state, labelsOrTypes, properties, options
                WHERE name = $name
                RETURN type, state, labelsOrTypes, properties, options
            """, name=SEMANTIC_INDEX_NAME))
            counts = session.run("""
                MATCH (e:Email)
                RETURN count(e) AS total,
                       count(e.aegis_embedding) AS embedded,
                       count(CASE WHEN e.aegis_embedding_model = $model
                                  THEN 1 END) AS current_model
            """, model=semantic_model_revision()).single()

        index = indexes[0] if indexes else None
        options = index["options"] if index else {}
        index_config = options.get("indexConfig", {})
        dimension = index_config.get("vector.dimensions")
        total = int(counts["total"]) if counts else 0
        embedded = int(counts["embedded"]) if counts else 0
        current_model = int(counts["current_model"]) if counts else 0
        index_ready = bool(
            index
            and index["type"] == "VECTOR"
            and index["state"] == "ONLINE"
            and index["labelsOrTypes"] == ["Email"]
            and index["properties"] == [SEMANTIC_VECTOR_PROPERTY]
            and dimension == 384
            and total > 0
            and embedded == total
            and current_model == total
        )
        model_available = False
        model_error = None
        if index_ready:
            try:
                self._get_semantic_model()
                model_available = True
            except RuntimeError as ex:
                model_error = str(ex)

        status = {
            "ready": index_ready and model_available,
            "index_ready": index_ready,
            "model_available": model_available,
            "model_error": model_error,
            "index": SEMANTIC_INDEX_NAME,
            "model": semantic_model_name(),
            "max_tokens": int(os.environ.get("AEGIS_EMBEDDING_MAX_TOKENS", "128")),
            "minimum_score": semantic_min_score(),
            "dimension": dimension,
            "embedded_emails": embedded,
            "total_emails": total,
        }
        self._semantic_status_cache = status
        self._semantic_status_checked_at = time.monotonic()
        return dict(status)

    def _supports_legacy_schema(self, session) -> bool:
        if self._legacy_schema_available is None:
            result = session.run("""
                CALL db.labels() YIELD label
                WITH collect(label) AS labels
                CALL db.relationshipTypes() YIELD relationshipType
                WITH labels, collect(relationshipType) AS relationship_types
                RETURN 'Employee' IN labels
                    AND 'Email' IN labels
                    AND 'SND_EMAIL' IN relationship_types
                    AND 'RCV_EMAIL' IN relationship_types AS supported
            """)
            record = result.single()
            self._legacy_schema_available = bool(record and record["supported"])
        return self._legacy_schema_available

    @staticmethod
    def _ranked_keyword_search(session, query: str, top_k: int):
        terms = _query_terms(query)
        if not terms:
            return []
        return list(session.run("""
            MATCH (s:Person)-[:SENT]->(m:Email)
            WITH s, m,
                 reduce(score = 0, term IN $terms |
                   score + CASE
                     WHEN toLower(coalesce(m.subject, '')) CONTAINS term THEN 3
                     WHEN toLower(coalesce(m.body, '')) CONTAINS term THEN 2
                     WHEN toLower(coalesce(s.name, '')) CONTAINS term
                       OR toLower(coalesce(s.email, '')) CONTAINS term THEN 1
                     WHEN EXISTS {
                       MATCH (m)-[:DISCUSSES]->(fallback_topic:Topic)
                       WHERE toLower(fallback_topic.name) CONTAINS term
                     } THEN 1
                     ELSE 0
                   END) AS lexical_score
            WHERE lexical_score > 0
            OPTIONAL MATCH (m)-[:SENT_TO]->(r:Person)
            OPTIONAL MATCH (m)-[:DISCUSSES]->(t:Topic)
            RETURN s, m, collect(DISTINCT r) AS recipients,
                   collect(DISTINCT t.name) AS topics,
                   max(toFloat(lexical_score) / size($terms))
                     AS relevance_score
            ORDER BY relevance_score DESC
            LIMIT $k
        """, terms=terms, k=top_k))

    def retrieve(self, query: str, top_k: int = 8) -> Dict[str, Any]:
        cypher_legacy = """
        MATCH (s:Employee)-[:SND_EMAIL]->(m:Email)-[:RCV_EMAIL]->(r:Employee)
        WHERE toLower(m.subject) CONTAINS toLower($q)
           OR toLower(m.body)    CONTAINS toLower($q)
           OR toLower(s.name)    CONTAINS toLower($q)
        RETURN s, m, collect(r) AS recipients, [] AS topics
        LIMIT $k
        """

        matched: List[Dict[str, Any]] = []
        node_ids: set = set()
        rels: List[Dict[str, str]] = []
        seen_relationships: set = set()

        def add_relationship(source: str, target: str, rel: str) -> None:
            key = (source, target, rel)
            if key not in seen_relationships:
                seen_relationships.add(key)
                rels.append({"source": source, "target": target, "rel": rel})

        session_kwargs = {"database": self.database} if self.database else {}
        with self._driver.session(**session_kwargs) as sess:
            status = self.semantic_index_status()
            if status["ready"]:
                try:
                    model = self._get_semantic_model()
                    encoded = model.encode(
                        query, normalize_embeddings=True, show_progress_bar=False
                    )
                    query_embedding = (
                        encoded.tolist()
                        if hasattr(encoded, "tolist")
                        else list(encoded)
                    )
                    result = list(sess.run("""
                        CALL db.index.vector.queryNodes(
                            $index, $candidate_limit, $embedding
                        ) YIELD node AS m, score
                        WHERE score >= $minimum_score
                        MATCH (s:Person)-[:SENT]->(m)
                        OPTIONAL MATCH (m)-[:SENT_TO]->(r:Person)
                        OPTIONAL MATCH (m)-[:DISCUSSES]->(t:Topic)
                        RETURN s, m, collect(DISTINCT r) AS recipients,
                               collect(DISTINCT t.name) AS topics,
                               max(score) AS relevance_score
                        ORDER BY relevance_score DESC
                        LIMIT $k
                    """, index=SEMANTIC_INDEX_NAME,
                        candidate_limit=max(top_k * 5, 40),
                        embedding=query_embedding, k=top_k,
                        minimum_score=semantic_min_score()))
                    retrieval_mode = "semantic"
                except Exception as ex:
                    log.warning(
                        "Neo4j vector retrieval failed; using ranked keyword "
                        "retrieval instead: %s",
                        ex,
                    )
                    result = self._ranked_keyword_search(sess, query, top_k)
                    retrieval_mode = "keyword_fallback"
            else:
                if status["index_ready"]:
                    log.warning(
                        "Neo4j vector index is ready, but the local semantic model "
                        "is unavailable (%s); using ranked keyword retrieval.",
                        status.get("model_error") or "model unavailable",
                    )
                    retrieval_mode = "keyword_fallback"
                else:
                    log.warning(
                        "Semantic Neo4j index is not ready (%s/%s emails embedded); "
                        "using ranked keyword retrieval.",
                        status["embedded_emails"], status["total_emails"],
                    )
                    retrieval_mode = "literal_fallback"

                result = self._ranked_keyword_search(sess, query, top_k)
            if not result and self._supports_legacy_schema(sess):
                result = list(sess.run(cypher_legacy, q=query, k=top_k))
                retrieval_mode = "legacy_literal_fallback"

            for rec in result:
                s = dict(rec["s"])
                m = dict(rec["m"])
                recs = [dict(r) for r in rec.get("recipients", [])]
                topics = list(rec.get("topics", []))

                sid = s.get("email") or s.get("id") or s.get("name")
                mid = m.get("email_id") or m.get("id") or m.get("subject")
                if not sid or not mid:
                    continue
                node_ids.add(sid); node_ids.add(mid)
                add_relationship(sid, mid, "SENT")

                recip_names = []
                for rr in recs:
                    rid = rr.get("email") or rr.get("id") or rr.get("name")
                    if rid:
                        node_ids.add(rid)
                        add_relationship(mid, rid, "SENT_TO")
                        recip_names.append(rr.get("name") or rid)

                date_val = m.get("sent_at") or m.get("date") or ""
                if isinstance(date_val, str) and len(date_val) > 10:
                    date_val = date_val[:10]

                matched.append({
                    "id": mid,
                    "subject": m.get("subject", "(No Subject)"),
                    "date": str(date_val),
                    "body": m.get("body", ""),
                    "sender": s.get("name") or s.get("email", ""),
                    "sender_department": s.get("department") or m.get("mailbox_owner", "Enron"),
                    "recipients": recip_names,
                    "topic": topics or m.get("topic", []),
                    "relevance_score": float(rec.get("relevance_score", 1.0)),
                })

        email_ids = {m["id"] for m in matched}
        return {
            "matched_emails": matched,
            "highlighted_node_ids": list(node_ids),
            "relationships": rels,
            "graph": {
                "nodes": [{"id": node_id, "label": node_id,
                           "type": "Email" if node_id in email_ids else "Person"}
                          for node_id in node_ids],
                "links": [r for r in rels if r["source"] in node_ids and r["target"] in node_ids],
            },
            "source": "neo4j",
            "retrieval_mode": retrieval_mode,
        }

    @staticmethod
    def _get_semantic_model():
        from .risk_engine import _get_embedder

        embedder = _get_embedder()
        if embedder is None:
            raise RuntimeError(
                "The semantic embedding model is unavailable; install/cache "
                f"{semantic_model_name()} before querying."
            )
        return embedder


def retrieve(query: str, neo4j: Optional[Neo4jRetriever] = None, top_k: int = 8) -> Dict[str, Any]:
    """Execute retrieval from the verified Neo4j connection only."""
    if neo4j is None:
        raise RuntimeError("Neo4j is not connected; retrieval is unavailable")
    try:
        return neo4j.retrieve(query, top_k=top_k)
    except Exception as ex:
        log.error("Neo4j retrieval failed: %s", ex)
        raise Neo4jUnavailableError(
            f"Neo4j query failed for the configured database: {ex}"
        ) from ex
