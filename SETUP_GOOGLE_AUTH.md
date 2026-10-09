# AegisGraph — Local run + Google OAuth (patched)

> For a fuller, Windows-specific walkthrough (Docker Mongo, OpenAI key, optional NLP extras, test fixtures), see [`LOCAL_SETUP_WINDOWS.md`](./LOCAL_SETUP_WINDOWS.md). This file covers just the Google OAuth piece.

This drop-in change replaces the Emergent Auth broker with **direct Google Identity Services (GIS)** using only your OAuth **Client ID** (no client secret needed).

## 1. Google Cloud Console
1. Go to https://console.cloud.google.com → APIs & Services → Credentials.
2. Create (or open) an **OAuth 2.0 Client ID** of type **Web application**.
3. Add **Authorized JavaScript origins**:
   - `http://localhost:3000`
   - (add your prod URL later)
4. Authorized redirect URIs can be left empty — GIS uses postMessage, not redirects.
5. Copy the Client ID (`...apps.googleusercontent.com`).

## 2. Env files
```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```
Put the **same** Client ID in both:
- `backend/.env`  → `GOOGLE_OAUTH_CLIENT_ID=...`
- `frontend/.env` → `REACT_APP_GOOGLE_CLIENT_ID=...`

Also in `backend/.env`:
- `MONGO_URL=mongodb://localhost:27017`
- `DB_NAME=aegisgraph`
- `AEGIS_COOKIE_INSECURE=1`  ← required so the session cookie works over http://localhost
- `CORS_ORIGINS=http://localhost:3000`  ← required, or the browser drops the session cookie on every call
- `OPENAI_API_KEY=` (optional — leave blank to use the built-in deterministic mock LLM)

## 3. Run
```bash
# terminal 1 — Mongo (Docker is easiest)
docker run -d --name mongo -p 27017:27017 mongo:7

# terminal 2 — backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload --port 8000

# terminal 3 — frontend
cd frontend
yarn install     # or: npm install
yarn start       # http://localhost:3000
```

## 4. What changed vs. the original
- `backend/server.py`
  - Removed `POST /api/auth/session` (Emergent broker call).
  - Added `POST /api/auth/google` that verifies a Google ID token via `oauth2.googleapis.com/tokeninfo`, checks `aud` == your Client ID, then creates / refreshes the user and issues an httpOnly session cookie exactly like before.
  - Cookie flags are now `Secure`/`SameSite=None` in prod and `Lax`/insecure in local dev when `AEGIS_COOKIE_INSECURE=1`.
- `frontend/src/pages/Login.jsx`
  - Loads Google Identity Services and renders the official Google button.
  - On credential callback → `POST /api/auth/google` → updates `AuthContext` → navigates to `/dashboard`.
- `frontend/src/components/AuthCallback.jsx`
  - Legacy Emergent hash-fragment handler neutralised (redirects home). Kept so any old bookmarks don't 404.
- `backend/.env.example`, `frontend/.env.example` — added.

**Everything else was untouched by *this* auth patch**: risk engine, moderation, KG retrieval, simulator, dashboard, history, profile, Neo4j fallback, demo data. `get_current_user`, `/auth/me`, `/auth/logout`, `PUT /me/role` all still work — the session cookie shape is identical. (A later pass did touch the LLM wrapper, risk engine, and dependencies to remove remaining Emergent-only ties — see [`GAP_REPORT.md`](./GAP_REPORT.md) for the full, current list.)

## 5. Neo4j
Neo4j is still optional. The app already falls back to the bundled Enron demo graph in `backend/aegis/demo_data.py` when the driver can't connect — no changes needed for your demo.
