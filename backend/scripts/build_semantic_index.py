"""Build or resume the additive Neo4j semantic email index."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from neo4j import GraphDatabase

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from aegis.kg_retrieval import (  # noqa: E402
    SEMANTIC_INDEX_NAME,
    SEMANTIC_VECTOR_PROPERTY,
    semantic_model_name,
    semantic_model_revision,
)
from aegis.risk_engine import _get_embedder  # noqa: E402


def _text(subject: str | None, body: str | None) -> str:
    return f"Subject: {subject or ''}\n\n{body or ''}"


def _build_index(session) -> None:
    session.run(f"""
        CREATE VECTOR INDEX {SEMANTIC_INDEX_NAME} IF NOT EXISTS
        FOR (e:Email) ON (e.{SEMANTIC_VECTOR_PROPERTY})
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: 384,
            `vector.similarity_function`: 'cosine'
        }}}}
    """).consume()


def _existing_index(session) -> Dict[str, Any] | None:
    record = session.run("""
        SHOW INDEXES
        YIELD name, type, state, labelsOrTypes, properties, options
        WHERE name = $name
        RETURN type, state, labelsOrTypes, properties, options
    """, name=SEMANTIC_INDEX_NAME).single()
    return dict(record) if record else None


def build(batch_size: int) -> None:
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if not (uri and user and password):
        raise RuntimeError("NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD are required in backend/.env")

    embedder = _get_embedder()
    if embedder is None:
        raise RuntimeError(
            f"Embedding model {semantic_model_name()} is unavailable. "
            "Check model download/cache and retry."
        )
    model = embedder
    token_limit = int(os.environ.get("AEGIS_EMBEDDING_MAX_TOKENS", "128"))
    if token_limit < 1 or token_limit > 512:
        raise RuntimeError("AEGIS_EMBEDDING_MAX_TOKENS must be between 1 and 512.")
    model.max_seq_length = token_limit
    get_dimension = getattr(
        model, "get_embedding_dimension", model.get_sentence_embedding_dimension
    )
    dimension = get_dimension()
    if dimension != 384:
        raise RuntimeError(
            f"Configured model has {dimension} dimensions; the Neo4j index "
            "requires 384. No database changes were made."
        )
    import torch
    threads = int(os.environ.get("AEGIS_EMBEDDING_THREADS", "8"))
    if threads < 1 or threads > 16:
        raise RuntimeError("AEGIS_EMBEDDING_THREADS must be between 1 and 16.")
    torch.set_num_threads(threads)

    driver = GraphDatabase.driver(uri, auth=(user, password))
    session_kwargs = {}
    database = os.environ.get("NEO4J_DATABASE")
    if database:
        session_kwargs["database"] = database

    try:
        with driver.session(**session_kwargs) as session:
            result = session.run("""
                MATCH (e:Email)
                RETURN count(e) AS total,
                       count(CASE WHEN e.email_id IS NULL THEN 1 END) AS missing_ids
            """).single()
            total = int(result["total"])
            missing_ids = int(result["missing_ids"])
            if total == 0 or missing_ids:
                raise RuntimeError(
                    f"Expected Email nodes with email_id; found total={total}, "
                    f"missing_ids={missing_ids}."
                )

            index = _existing_index(session)
            if index:
                options = index.get("options") or {}
                index_config = options.get("indexConfig", {})
                existing_dimension = index_config.get("vector.dimensions")
                if (
                    index["type"] != "VECTOR"
                    or index["labelsOrTypes"] != ["Email"]
                    or index["properties"] != [SEMANTIC_VECTOR_PROPERTY]
                    or existing_dimension != dimension
                ):
                    raise RuntimeError(
                        f"Existing index {SEMANTIC_INDEX_NAME} conflicts with "
                        "the configured model. No index was changed."
                    )

            print(
                f"Embedding {total:,} Email nodes with {semantic_model_name()} "
                f"({dimension} dimensions, {token_limit} tokens), "
                f"batch size {batch_size}."
            )
            cursor = ""
            processed = 0
            updated = 0
            started = time.monotonic()

            while True:
                records = list(session.run("""
                    MATCH (e:Email)
                    WHERE e.email_id > $cursor
                    RETURN e.email_id AS id,
                           e.aegis_embedding IS NOT NULL AS has_embedding,
                           e.aegis_embedding_model AS model,
                           CASE WHEN e.aegis_embedding_model = $model
                                     AND e.aegis_embedding IS NOT NULL
                                THEN null ELSE e.subject END AS subject,
                           CASE WHEN e.aegis_embedding_model = $model
                                     AND e.aegis_embedding IS NOT NULL
                                THEN null ELSE substring(e.body, 0, 2048) END AS body
                    ORDER BY e.email_id
                    LIMIT $batch_size
                """, cursor=cursor, batch_size=batch_size,
                    model=semantic_model_revision()))
                if not records:
                    break

                rows: List[Dict[str, Any]] = []
                texts: List[str] = []
                for record in records:
                    cursor = record["id"]
                    processed += 1
                    if (
                        record["has_embedding"]
                        and record["model"] == semantic_model_revision()
                    ):
                        continue
                    rows.append({"id": record["id"]})
                    texts.append(_text(record["subject"], record["body"]))

                if rows:
                    vectors = model.encode(
                        texts,
                        batch_size=min(batch_size, 64),
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    for row, vector in zip(rows, vectors):
                        row["embedding"] = vector.tolist()
                        row["model"] = semantic_model_revision()
                    session.run("""
                        UNWIND $rows AS row
                        MATCH (e:Email {email_id: row.id})
                        SET e.aegis_embedding = row.embedding,
                            e.aegis_embedding_model = row.model
                    """, rows=rows).consume()
                    updated += len(rows)

                if processed % (batch_size * 10) < len(records):
                    elapsed = max(time.monotonic() - started, 0.001)
                    rate = processed / elapsed
                    print(
                        f"Progress: {processed:,}/{total:,} checked; "
                        f"{updated:,} embedded in this run "
                        f"({rate:.0f} emails/sec).",
                        flush=True,
                    )

            _build_index(session)
            print(f"Waiting for vector index {SEMANTIC_INDEX_NAME} to become ONLINE...")
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                index = _existing_index(session)
                if index and index["state"] == "ONLINE":
                    break
                if index and index["state"] == "FAILED":
                    raise RuntimeError(
                        f"Neo4j reports vector index {SEMANTIC_INDEX_NAME} as FAILED."
                    )
                time.sleep(2)
            else:
                raise TimeoutError(
                    f"Vector index {SEMANTIC_INDEX_NAME} did not become ONLINE within 15 minutes."
                )

            counts = session.run("""
                MATCH (e:Email)
                RETURN count(e) AS total,
                       count(e.aegis_embedding) AS embedded,
                       count(CASE WHEN e.aegis_embedding_model = $model
                                  THEN 1 END) AS current_model
            """, model=semantic_model_revision()).single()
            if (
                int(counts["total"]) != total
                or int(counts["embedded"]) != total
                or int(counts["current_model"]) != total
            ):
                raise RuntimeError(
                    "Semantic index coverage verification failed: "
                    f"total={counts['total']}, embedded={counts['embedded']}, "
                    f"current_model={counts['current_model']}."
                )

            print(
                f"Ready: {counts['embedded']:,}/{counts['total']:,} Email nodes "
                f"embedded; vector index ONLINE."
            )
    finally:
        driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=512)
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 512:
        parser.error("--batch-size must be between 1 and 512")
    build(args.batch_size)
