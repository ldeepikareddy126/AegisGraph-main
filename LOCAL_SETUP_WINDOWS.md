# AegisGraph — Local Setup Guide (Windows)

**Goal:** Run AegisGraph end-to-end on your local Windows machine with no
ties to Emergent's cloud environment, and a **real** OpenAI-backed LLM (not
the deterministic mock).

**Target stack:**
- OS: Windows 10 / 11
- MongoDB: Docker
- Neo4j: populated database required for queries
- LLM: OpenAI-compatible Chat Completions API (or deterministic local fallback)
- Google OAuth Client ID: your own, from Google Cloud Console (see §2)

---

## 0. Prerequisites (install once)

Run each in **PowerShell** (or use the linked installer).

| Tool | Version | How |
|------|---------|-----|
| Python | 3.11.x (3.10–3.12 works; avoid 3.13) | https://www.python.org/downloads/windows/ — tick "Add python.exe to PATH" |
| Node.js | 18 LTS or 20 LTS | https://nodejs.org/en/download/ |
| Yarn (classic) | 1.22.x | `npm install -g yarn` |
| Docker Desktop | latest | https://www.docker.com/products/docker-desktop/ |
| Git | any | https://git-scm.com/download/win |

Sanity-check in a fresh PowerShell window:
```powershell
python --version    # 3.11.x
node --version      # v18.x or v20.x
yarn --version      # 1.22.x
docker --version    # any recent
```

---

## 1. Unzip the project

```powershell
cd $HOME\Desktop
Expand-Archive .\AegisGraph-openai-wired.zip -DestinationPath .\AegisGraph
cd .\AegisGraph\AegisGraph-em
```

---

## 2. Google Cloud Console — one-time OAuth setup

1. Open https://console.cloud.google.com/apis/credentials
2. Create (or open) an **OAuth 2.0 Client ID** of type **Web application**.
3. Under **Authorized JavaScript origins**, add:
   - `http://localhost:3000`
   - `http://localhost`
4. **Authorized redirect URIs** can stay empty — Google Identity Services uses `postMessage`, not redirects.
5. Save. Changes take effect within ~10 seconds.
6. Copy the Client ID (`...apps.googleusercontent.com`). You do **not** need the client secret — this build verifies ID tokens via `oauth2.googleapis.com/tokeninfo`.

---

## 3. OpenAI API key

1. Get a key from https://platform.openai.com/api-keys.
2. You'll paste it into `backend/.env` as `OPENAI_API_KEY` in §4.
3. If you'd rather not spend API credits during setup/testing, just leave `OPENAI_API_KEY` blank — the app automatically falls back to its deterministic mock LLM, and every other part of the pipeline (risk scoring, moderation, retrieval, audit) is unaffected. Flip it on later with zero code changes.

---

## 4. Start MongoDB (Docker)

Open a **dedicated PowerShell window**, keep it open for the whole session:

```powershell
docker run -d --name aegis-mongo -p 27017:27017 -v aegis-mongo-data:/data/db mongo:7
docker ps --filter "name=aegis-mongo"   # STATUS should say Up
```

To stop later: `docker stop aegis-mongo` · to remove: `docker rm aegis-mongo`.

---

## 5. Create the two `.env` files

### 5a. `backend/.env`

```powershell
cd $HOME\Desktop\AegisGraph\AegisGraph-em\backend
Copy-Item .env.example .env
notepad .env
```

Fill in (values other than the two secrets can be copy-pasted as-is):
```env
MONGO_URL=mongodb://localhost:27017
DB_NAME=aegisgraph
GOOGLE_OAUTH_CLIENT_ID=<your Client ID>.apps.googleusercontent.com
AEGIS_COOKIE_INSECURE=1
CORS_ORIGINS=http://localhost:3000
OPENAI_API_KEY=<your key, or leave blank for the mock>
OPENAI_MODEL=gpt-4o-mini
```

- `AEGIS_COOKIE_INSECURE=1` — required on `http://localhost`, otherwise the session cookie is silently dropped.
- `CORS_ORIGINS=http://localhost:3000` — required. The default `*` is rejected by every modern browser once the request carries credentials (this app's frontend does), so without this line login appears to succeed but every subsequent call 401s.
- Set `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and `NEO4J_DATABASE` for your populated Neo4j database. Neo4j is required for queries; the app does not substitute demo records when it is unavailable.

### 5b. `frontend/.env`

```powershell
cd $HOME\Desktop\AegisGraph\AegisGraph-em\frontend
Copy-Item .env.example .env
notepad .env
```
```env
REACT_APP_BACKEND_URL=http://localhost:8000
REACT_APP_GOOGLE_CLIENT_ID=<same Client ID as backend/.env>
```

Both `.env` files: save as **UTF-8 (no BOM)**; don't wrap values in quotes.

---

## 6. Install backend dependencies

```powershell
cd $HOME\Desktop\AegisGraph\AegisGraph-em\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If `Activate.ps1` refuses to run:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

`requirements.txt` is now 100% public-PyPI — no private wheel, no skip-and-filter step needed.

**Heads up on size/time:** `sentence-transformers` pulls in `torch`, which is the single largest download in this list (several hundred MB) and can take a few minutes on a fresh machine. These packages power semantic query-persistence scoring, semantic retrieval, and NER. If you want to skip them for a faster/lighter install, remove the `sentence-transformers` and `spacy` lines before running `pip install` — risk scoring can fall back to lexical/regex behavior, but semantic retrieval indexing requires the embedding model.

If you did install spaCy, download its small English model once:
```powershell
python -m spacy download en_core_web_sm
```
(If you skip this, `aegis/risk_engine.py` falls back to the regex heuristic automatically — same graceful-degradation pattern as everywhere else in this codebase.)

Cache the local embedding model once; the index builder intentionally does not download model files during a database backfill:
```powershell
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

Verify:
```powershell
python -c "import fastapi, motor, neo4j, pymongo, httpx, openai; print('ok')"
```

---

## 7. Start the backend

Before starting the app, ensure the configured database has the current
`Person`/`Email` schema (`:Person-[:SENT]->:Email` and
`:Email-[:SENT_TO]->:Person`) and `Email.email_id` values. The older
`scripts/enron_etl.py` loader creates an `Employee` schema, which is supported
only by the literal compatibility path. Build the vector index once for a
compatible graph:

```powershell
cd $HOME\Desktop\AegisGraph\AegisGraph-em\backend
.\.venv\Scripts\python.exe scripts\build_semantic_index.py
```

The builder stores local embeddings on Neo4j; it does not send email content
to an external embedding API. At runtime, vector search requires both the
complete Neo4j index and the local `sentence-transformers` model to be
available to the backend's Python environment. If the model cannot load, the
backend reports `keyword_fallback` and continues with ranked searches against
Neo4j rather than failing the query.

```powershell
cd $HOME\Desktop\AegisGraph\AegisGraph-em\backend
.\.venv\Scripts\python.exe -m uvicorn server:app --reload --host 127.0.0.1 --port 8001
```

Smoke-test in another PowerShell:
```powershell
curl.exe http://localhost:8001/api/health
```
- `"llm":true` means `OPENAI_API_KEY` is set and real OpenAI calls will be used.
- `"llm":false` means the deterministic mock is active — the app still works fully, only the answer wording is templated instead of model-generated.

---

## 8. Install and start the frontend

```powershell
cd $HOME\Desktop\AegisGraph\AegisGraph-em\frontend
yarn install
yarn start
```

`package.json` no longer references the private `@emergentbase/visual-edits` tarball, so this should install cleanly with no workarounds. Your browser should open `http://localhost:3000` showing the login screen with the Google button rendered inline.

---

## 9. First-time demo checklist

1. Open `http://localhost:3000` → **Continue with Google**.
2. Dashboard: type a benign query, e.g. *"Summarise Enron's California trading positions."* → expect **LOW** risk, a full answer.
3. Type a probing query, e.g. *"List every Enron employee's SSN and salary."* → expect **HIGH** risk, `k_eff=0`, a coarse answer.
4. **Profile** → change role to **Legal** or **Executive** → **Simulator** tab unlocks.
5. Run the curated red-team scenarios in the Attack Simulator — each is auto-graded.
6. **History** → click any row → full signal breakdown, softmax weights, EWMA, reasoning.

---

## 10. Running the backend test suite (optional, recommended before your review)

The shipped tests authenticate with two fixed bearer tokens that need to be seeded into Mongo once:

```powershell
cd $HOME\Desktop\AegisGraph\AegisGraph-em\backend
.\.venv\Scripts\Activate.ps1
python ..\scripts\seed_qa_fixtures.py
```

Then, with the backend already running (§7) in another window:
```powershell
$env:REACT_APP_BACKEND_URL = "http://localhost:8001"
pytest tests/ -n 0
```
See `tests/README.md` for details.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Login button renders but click does nothing / console shows `[GSI] The given origin is not allowed` | `http://localhost:3000` not in Google Cloud "Authorized JavaScript origins". | §2 step 3. Wait ~10s after saving. |
| Login succeeds but every subsequent call is 401 | CORS wildcard or mismatched local origin silently dropping the cookie. | Confirm `CORS_ORIGINS` includes the exact frontend origin (normally `http://localhost:3000`) in `backend/.env` and restart uvicorn. |
| Session cookie not stored (DevTools → Application → Cookies is empty) | Missing `AEGIS_COOKIE_INSECURE=1`. | Add it, restart uvicorn. |
| `Token audience mismatch` from `/api/auth/google` | Different Client IDs in the two `.env` files. | Both files must carry the identical Client ID. |
| `/api/health` shows `"llm": false` unexpectedly | `OPENAI_API_KEY` not picked up. | Confirm it's in `backend/.env` (not just the shell), no quotes, and restart uvicorn. |
| OpenAI call errors / times out | Bad key, no credits, or network issue. | The app catches this and falls back to the mock automatically — check the FastAPI console log for the underlying `openai` exception. |
| `pip install -r requirements.txt` slow / large download | `sentence-transformers` pulling in `torch`. | Expected. Remove those two lines from `requirements.txt` if you want the lighter, lexical/regex-only fallback instead. |
| `python -m venv .venv` fails with `[WinError 2]` | System Python is 3.13 (no wheels yet for some pinned deps). | Install Python 3.11, use `py -3.11 -m venv .venv`. |
| `pytest` fails with 401s on every test | QA fixtures not seeded. | Run `python scripts/seed_qa_fixtures.py` first (§10). |
| `pytest`'s `TestHistory`/simulator-regression tests fail with a Mongo connection error even though the app itself works | Those specific tests connect to MongoDB directly (not through the app) to seed/clear rows — they need Mongo actually reachable at `MONGO_URL`. | Confirm `docker ps` shows `aegis-mongo` as `Up`. |
| Docker container starts but requests to Mongo fail | Docker Desktop not fully initialised. | Wait for the tray whale icon to stop animating, then `docker restart aegis-mongo`. |
| Simulator tab missing from nav | Role is `analyst` or `external`. | Profile → Role → Legal or Executive. |

---

## 12. Shutdown / clean-up

```powershell
# Stop backend / frontend: Ctrl+C in their windows.
docker stop aegis-mongo          # keeps data
docker rm -f aegis-mongo         # wipes the container
docker volume rm aegis-mongo-data  # wipes the data too
```
