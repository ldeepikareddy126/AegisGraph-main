# Auth Testing Playbook

Auth is direct Google Identity Services + backend ID-token verification —
see `SETUP_GOOGLE_AUTH.md`. This file is a reminder about manually creating
a test session without going through a real Google login.

## Endpoints
- `POST /api/auth/google`   — verify a Google ID token (`credential`), create/refresh the user, issue a session cookie
- `GET  /api/auth/me`       — returns current user (cookie or bearer)
- `POST /api/auth/logout`  — invalidates session and clears cookie

## Preferred: seeded QA fixtures
`scripts/seed_qa_fixtures.py` creates two ready-to-use accounts (external +
legal role) with fixed bearer tokens `tok_ext_qa` / `tok_legal_qa` — this is
what `backend/tests/` uses. See `backend/tests/README.md`.

## Manual one-off test session
```
mongosh --eval "
use('aegisgraph');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({user_id:userId,email:'qa+' + Date.now() + '@aegis.test',name:'QA Tester',picture:null,role:'analyst',linked_employee:null,department:null,created_at:new Date().toISOString()});
db.user_sessions.insertOne({user_id:userId,session_token:sessionToken,expires_at:new Date(Date.now()+7*24*60*60*1000).toISOString(),created_at:new Date().toISOString()});
print('TOKEN=' + sessionToken);
"
```

Then hit protected endpoints with `Authorization: Bearer <TOKEN>` or with
the `session_token` cookie set to the same value. Swap `role` to
`external` / `manager` / `executive` / `legal` as needed (Simulator access
requires `legal` or `executive`).
