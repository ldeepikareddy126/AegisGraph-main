# AegisGraph — Current Consistency Snapshot

This snapshot describes the current implementation, including the Neo4j-only
retrieval and semantic vector index. The historical change notes below are
retained for context; current behavior is defined by the component status.

## 1. What changed in this pass

| # | Area | Before | After |
|---|------|--------|-------|
| 1 | LLM (`backend/aegis/llm.py`) | Previously tied to a private provider integration. | Uses an OpenAI-compatible Chat Completions HTTP endpoint (`OPENAI_MODEL`, default `gpt-4o-mini`, Groq-compatible when configured); deterministic local response when no key is set or providers fail. |
| 2 | Semantic risk signal (`backend/aegis/risk_engine.py`) | Lexical matching only. | `S_sem` measures semantic persistence against recent session queries using `all-MiniLM-L6-v2`; lexical overlap is used if the model is unavailable. Sensitive terms remain a separate lexical hard-gate/reasoning input. It does not currently compute semantic sensitivity against exemplars. |
| 3 | Entity extraction (`backend/aegis/risk_engine.py`) | Regex capitalised-bigram heuristic for names, plus regex for PII. | Real spaCy NER (`en_core_web_sm`, `PERSON`/`ORG`/`GPE`) for names/orgs/places. Regex is kept (correctly) for structured PII — SSNs, phones, emails — since that's the right tool for that job regardless of NER. Falls back to the original bigram heuristic if spaCy/model isn't installed. |
| 4 | `backend/requirements.txt` | Pinned `emergentintegrations==0.2.0` (private, not on PyPI — `pip install` fails on any machine outside Emergent). | That line removed; added `openai`, `sentence-transformers`, `spacy` (all public PyPI packages). |
| 5 | `frontend/package.json` / `craco.config.js` | Hard devDependency on `@emergentbase/visual-edits`, fetched from a private tarball URL (`assets.emergent.sh`) that 404s off-platform — `yarn install` fails outside Emergent. | Dependency and its dead `require(...)` block removed outright. This was a dev-only visual-editing overlay for Emergent's own platform; it has no effect on the app's functionality. |
| 6 | `backend/.env.example` | `EMERGENT_LLM_KEY=` placeholder; no `CORS_ORIGINS`. | `OPENAI_API_KEY` / `OPENAI_MODEL`, `CORS_ORIGINS` (required — see §3), and documented opt-out flags for the new NLP backends. |
| 7 | Test suite runnability | `tests/backend_test.py` / `tests/test_simulator.py` hardcode bearer tokens `tok_ext_qa` / `tok_legal_qa` that **nothing in the repo ever created** — the suite could never actually authenticate, a gap the previous report missed entirely. | Added `scripts/seed_qa_fixtures.py`, an idempotent seeder that creates the two matching `users`/`user_sessions` documents directly in Mongo. Documented in `tests/README.md`. |

## 2. Component-by-component status (paper alignment)

| # | Component | Status | Evidence | Notes |
|---|-----------|--------|----------|-------|
| 1 | Google OAuth (end-to-end) | Working | `backend/server.py` `/api/auth/google`; `frontend/src/pages/Login.jsx` | Direct Google Identity Services + ID-token verification via `oauth2.googleapis.com/tokeninfo`. No client secret needed. Unchanged in this pass. |
| 2 | RBAC | Working | `aegis/risk_engine.py` (`ROLE_PROFILES`), `PUT /me/role`, simulator gate | Unchanged in this pass. |
| 3 | Session tracking | **Scoped** | `server.py` session cookie + `db.user_sessions` | Behavioral query history and EWMA are scoped to the authenticated login session; simulator traffic remains auditable but does not influence behavioral history. |
| 4 | Query preprocessing | Working | `server.py`, `aegis/risk_engine.py` | Unchanged in this pass. |
| 5 | Semantic persistence signal | **Upgraded** | `aegis/risk_engine.py` `_semantic_persistence` / `_get_embedder` | Compares the current query with recent session queries. |
| 6 | Entity extraction | **Upgraded** | `aegis/risk_engine.py` `detect_entities` / `_get_nlp` | Now real spaCy NER for names/orgs/places, regex kept for structured PII. Optional — degrades gracefully. |
| 7 | Behavior Analysis Engine | Working | `aegis/risk_engine.py` | Four signals (`S_sem`, `S_temp`, `S_ent`, `S_graph`) feed the fixed weighted sum, corroboration boost, EWMA, role adjustment, and hard gates. |
| 8 | Graph Retrieval | **Neo4j required** | `aegis/kg_retrieval.py`, `server.py` | Uses semantic vector search when the index is complete; otherwise reports a literal compatibility mode. There is no demo-data retrieval fallback; missing/unusable Neo4j produces HTTP 503. |
| 9 | Signal Fusion Engine | Working | `aegis/risk_engine.py` | Fixed weighted sum plus pairwise corroboration boost; weights persisted per turn. |
| 10 | Risk Assessment Engine (EWMA) | Working | `aegis/risk_engine.py`, `server.py` | Unchanged in this pass. |
| 11 | Adaptive Decision Engine | **Separate disclosure policy** | `aegis/disclosure.py`, `aegis/moderation.py`, `server.py` | Behavioral score and tier remain paper-defined. An independent disclosure gate may make effective handling stricter for direct PII/credential or bulk confidential-data requests; MEDIUM exposes at most three redacted records, sanitizes generated identifiers and monetary amounts, and may disclose a qualified employee-record aggregate on explicit roster/count requests. HIGH withholds exact counts. |
| 12 | Response Controller | **Upgraded** | `aegis/llm.py`, `server.py` | Now calls real OpenAI when `OPENAI_API_KEY` is set; same moderated-context contract either way. |
| 13 | Audit logging | Working | `server.py`, `/api/history` | Unchanged in this pass. |
| 14 | User profiling | Working | `server.py` | Unchanged in this pass. |
| 15 | Explainability layer | Working | `aegis/risk_engine.py`, `server.py` | Reports signal values, weights, risk adjustments, and human-readable reasoning. Retrieval mode and relevance are also returned for semantic searches. |

The locally configured Neo4j database was verified with 251,449 Email nodes;
all 251,449 were embedded for `all-MiniLM-L6-v2` and the vector index was
ONLINE. The default relevance cutoff is 0.75 and remains configurable.

## 3. Configuration still required (env-only, unchanged from before)

| Issue | Fix |
|---|---|
| CORS default `*` rejected by browsers once cookies are involved | `CORS_ORIGINS=http://localhost:3000` in `backend/.env` |
| Session cookie dropped on plain `http://localhost` | `AEGIS_COOKIE_INSECURE=1` in `backend/.env` |
| Google Identity Services rejects unlisted origins | Add `http://localhost:3000` under "Authorized JavaScript origins" for your OAuth Client ID |

## 4. Retrieval and optional-model behavior

- **Neo4j is required for queries.** `aegis/demo_data.py` remains for profile defaults, redaction support, and fixtures, but is not a retrieval fallback. Complete-index and local-model readiness are reported separately; if vector retrieval cannot run, the app uses ranked keyword retrieval from the configured Neo4j database rather than failing the query.
- **Older ETL schema:** `scripts/enron_etl.py` creates `Employee`/`SND_EMAIL`/`RCV_EMAIL`, which can be served only through the literal compatibility path. Semantic retrieval expects the current `Person`/`SENT`/`SENT_TO` schema; the index builder also requires `Email.email_id`.
- **Optional NLP models:** if `sentence-transformers` or spaCy/model files are unavailable, risk scoring falls back to lexical query similarity and regex entity extraction. If the local sentence-transformer model is unavailable to the backend process, retrieval falls back to ranked Neo4j keyword search and reports that mode; the semantic retrieval index builder itself requires the embedding model to be available locally.
- **Semantic sensitivity is not an embedding score.** `S_sem` measures query persistence, while sensitive-term detections are lexical. A semantic sensitivity score against exemplars would be a risk-model change and is intentionally not introduced by this consistency pass.
- **Temporal request counting:** the current request is included in the trailing 60-second window using its issue timestamp; future timestamps are excluded. Only authenticated-session behavioral history is considered, and simulator-origin runs are audit-only.

## 5. Known limitation surfaced in this pass (test suite)

`tests/backend_test.py::TestHistory` and several `tests/test_simulator.py` fixtures connect **directly** to a live MongoDB via raw `pymongo` (bypassing the app) to seed/clear history rows for test isolation. Those specific tests require a genuinely running MongoDB reachable at `MONGO_URL` — there's no way around that with a mock, and there shouldn't be, since that's exactly what they're testing. Everything else (auth, RBAC, the full query → risk → moderation → response pipeline, the Attack Simulator) has been exercised end-to-end against the real application code with an in-memory Mongo substitute and passed. Run the full suite against your real local Mongo per `tests/README.md` for the final check before your review.
