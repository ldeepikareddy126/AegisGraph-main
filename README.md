# AegisGraph

A behavior-aware, risk-adaptive RAG system over an Enron-style email corpus:
every query is scored across four behavioral signals (semantic persistence
across recent session queries, query frequency, entity concentration,
graph-traversal proximity), fused via
a fixed, interpretable weighted sum with corroboration, smoothed with an EWMA,
and used to adaptively moderate what reaches the LLM — up to six unredacted
records at LOW risk, redacted/truncated context at MEDIUM, a coarse
topic-only hint at HIGH. Behavioral risk and disclosure policy are separate:
direct requests for identifiers or credentials can trigger stricter disclosure
without changing the behavioral score. MEDIUM responses also redact generated
identifiers and monetary amounts; explicit workforce-count or full-roster
requests can receive a qualified aggregate count from `Person.is_employee`,
without releasing names. HIGH responses do not disclose exact workforce counts.

- **Auth:** Google Identity Services + ID-token verification (no client secret).
- **LLM:** OpenAI (`gpt-4o-mini` by default), with a deterministic mock fallback if no API key is configured.
- **Storage:** MongoDB (audit log, sessions, users).
- **Graph retrieval:** Neo4j only. Email search uses semantic vector retrieval when both the complete vector index and local embedding model are available. If either is unavailable, the API reports and uses a ranked keyword fallback against Neo4j; it never substitutes demo records.
- **Graph status:** Connectivity is checked with a lightweight Neo4j ping; graph-size counts are cached for one minute rather than rescanning the full graph on each UI status refresh.
- **Admin activity:** Administrators have a read-only account activity page with cross-account query analytics and paginated account histories. Query text and generated summaries can be sensitive; these API routes require the `admin` role.
- **Frontend:** React (CRA + craco).

## Getting started

See **[`LOCAL_SETUP_WINDOWS.md`](./LOCAL_SETUP_WINDOWS.md)** for a full,
copy-paste local setup (Windows + Docker Mongo). The steps translate
directly to macOS/Linux — swap PowerShell syntax for your shell.

### Build the Neo4j semantic email index

With Neo4j running and `backend/.env` configured, run once from the project
root:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe scripts\build_semantic_index.py
```

This creates normalized `all-MiniLM-L6-v2` embeddings for the Neo4j `Email`
nodes and an additive Neo4j vector index. It processes records in batches and
can be rerun to resume/verify the index. The backend status endpoint reports
semantic-index and local-model readiness separately. Queries use vector
similarity when both are ready; otherwise they use an explicitly reported
ranked Neo4j keyword fallback until the index or model is available.
Embeddings use the
subject and message text truncated to the model's 128-token input window by
default (`AEGIS_EMBEDDING_MAX_TOKENS` can increase it at a higher indexing
cost); results below cosine similarity 0.75 are discarded by default
(`AEGIS_SEMANTIC_MIN_SCORE` is configurable). Batches run locally and do not
send email content to an external API.

For just the Google OAuth piece, see [`SETUP_GOOGLE_AUTH.md`](./SETUP_GOOGLE_AUTH.md).

### Administrator access

`admin`, `legal`, and `executive` are privileged roles and cannot be self-assigned.
For the first administrator, have the intended Google account sign in once, then
assign `admin` to that exact account in MongoDB using an authorized database
operator. For the local Docker setup, the command is:

```powershell
docker exec aegis-mongo mongosh aegisgraph --quiet --eval 'db.users.updateOne({email: "admin@example.com"}, {$set: {role: "admin"}})'
```

Replace `aegisgraph` with the configured `DB_NAME` if different, and replace
the example with the verified account email. Confirm MongoDB reports
`matchedCount: 1` and `modifiedCount: 1` (or that the existing role was already
`admin`). Do not use a broad update filter. The user should sign out and back in;
the Admin Activity link then appears. Its account list is limited to accounts
with query history, and query history is accessible only through the
administrator-protected API. Regular users retain access only to their own
history.

## Project status

See [`GAP_REPORT.md`](./GAP_REPORT.md) for a full component-by-component
audit against the paper, what changed in the most recent pass, and what
remains an intentional (documented, gracefully-degrading) deviation.

## Running the tests

See [`backend/tests/README.md`](./backend/tests/README.md).

## Repo layout

```
backend/    FastAPI app, risk engine, moderation, KG retrieval, LLM wrapper
frontend/   React app (CRA + craco)
scripts/    Data ETL (enron_etl.py) and QA test-fixture seeding
tests/      (top-level) auth/manual test notes — see backend/tests/ for the automated suite
```
