# AegisGraph — PRD

## Original problem statement
Build a polished proof-of-concept web app **AegisGraph — Privacy-Aware
Security Framework for RAG using Knowledge Graphs** (Enron Email dataset).
ChatGPT-style UI that retrieves from Neo4j, calculates a privacy risk score,
moderates the retrieved context, and generates a natural-language answer.

## Users & personas
1. **Faculty mentor / reviewer** – wants to demonstrate the paper's flow end
   to end, without setting up Neo4j.
2. **Enterprise analyst (employee)** – legitimate access to the graph;
   should get a small clearance discount on risk.
3. **External researcher** – no clearance; should get a bump.

## Architecture
- **Frontend**: React + TailwindCSS + shadcn/ui, `react-force-graph-2d`,
  `recharts`, `framer-motion`.
- **Backend**: FastAPI + Motor (Mongo) + optional Neo4j driver.
- **LLM**: OpenAI (`gpt-4o-mini` by default, configurable via `OPENAI_MODEL`);
  deterministic mock fallback ensures the demo never fails even without an
  API key. (Originally Claude Sonnet 4.5 via Emergent Universal Key — swapped
  out so the project has no Emergent-platform ties; see `GAP_REPORT.md`.)
- **Auth**: Direct Google Identity Services + backend ID-token verification
  (`/api/auth/google` → `oauth2.googleapis.com/tokeninfo`), no client secret.
  session_id → httpOnly cookie downstream, unchanged. (Originally routed
  through an Emergent-managed broker — see `SETUP_GOOGLE_AUTH.md`.)

## Core requirements
- ChatGPT-style query playground.
- Six-step retrieval pipeline visualised with animated stepper.
- LOW / MEDIUM / HIGH risk moderation:
  - LOW: full detailed answer.
  - MEDIUM: names, emails, phones, SSNs redacted from context.
  - HIGH: vague, high-level summary (**never** a bare refusal).
- User-aware risk: role (external/analyst/manager/executive/legal) is
  factored into the score.
- Persistent history of every query for every user.
- History search + CSV export.
- Per-user risk-trend chart with LOW/MED/HIGH threshold bands.
- Neo4j connect modal (bolt URI / user / pw / test); graceful fall-through
  to a rich in-memory Enron corpus (31 employees, 260 emails, 798 rels)
  that mimics the live graph.
- Force-directed KG viz with highlighted subgraph for the current query.

## What's implemented (as of 2026-07-24)
- ✅ Google sign-in (direct Google Identity Services + ID-token verification), cookie session, 7-day expiry.
- ✅ Six-step pipeline + animated stepper + KG viz + analysis panel.
- ✅ Attention-fused risk engine (semantic, temporal, entity, graph signals;
      softmax weights; EWMA smoothing; role bump).
- ✅ Vague-but-substantive HIGH-risk responses via topic hint.
- ✅ Redaction badges shown in the UI.
- ✅ Persistent history in Mongo; search + CSV export; red-team badge for
      simulator-originated queries.
- ✅ Risk-trend page (Recharts) with adjusted/ewma dual line, thresholds,
      average score, per-level distribution.
- ✅ Role editor on Profile page.
- ✅ Neo4j connect + graceful demo fallback (indistinguishable from live).
- ✅ Documented Enron maildir → CSV → Neo4j ETL (`/app/scripts/enron_etl.py`).
- ✅ **Attack Simulator** (role-gated to legal/executive): 7 curated red-team
      scenarios (control, prompt-injection, PII probing, aggregation,
      role-escalation, chained injection, temporal burst); one-click run,
      pipeline animation, per-scenario grade against expected outcome.
- ✅ **Prompt-injection role override**: any query containing injection
      markers revokes a privileged role's discount and adds a +0.10 penalty,
      so obvious injections always trigger HIGH.
- ✅ **Compare View**: side-by-side execution of the same scenario across
      two roles (any of external/analyst/manager/executive/legal), showing
      pipeline, redactions, k_eff, adjusted score and a generated insight
      line. Ephemeral: not written to history.

## Backlog (P1 / P2)
- **P1** Streaming AI responses (SSE) instead of single JSON reply.
- **P1** Query-level "explain this decision" drill-down modal.
- **P1** Interceptor to bounce user to `/` on 401 (from testing-agent code review).
- **P2** Convert `@app.on_event('shutdown')` → FastAPI lifespan.
- **P2** Multi-hop retrieval + Cypher path visualisation on the KG viz.
- **P2** Admin view aggregating risk-level distributions across all users.
- **P2** Realtime query rate-limit + soft-lockout after 5 HIGH-risk hits.

## Test credentials
QA bearer tokens (`tok_ext_qa`, `tok_legal_qa`) used by the automated test
suite aren't created automatically — run `scripts/seed_qa_fixtures.py` once
to seed them. See `backend/tests/README.md` for details.
