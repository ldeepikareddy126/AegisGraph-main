# Backend tests

`backend_test.py` and `test_simulator.py` are HTTP-level integration tests —
they run against a **live** server, not in-process.

## One-time fixture setup

Both files authenticate with two fixed bearer tokens:

- `tok_ext_qa` — an `external`-role QA user
- `tok_legal_qa` — a `legal`-role QA user (needed for Simulator access)

Nothing in the app creates these on its own — they have to be seeded into
Mongo once before the suite can log in:

```bash
python ../scripts/seed_qa_fixtures.py
```

This is idempotent — safe to re-run any time (e.g. after wiping the Mongo
volume).

## Running

With MongoDB running and the backend server started separately:

```bash
export REACT_APP_BACKEND_URL=http://localhost:8000   # or wherever uvicorn is listening
pytest tests/ -n 0
```

`-n 0` disables `pytest-xdist` parallelism — some classes (notably
`TestHistory`) depend on ordering / shared state and are not safe to run
across parallel workers.

## Note on `TestHistory` and the simulator regression tests

A few fixtures in these files (e.g. `_clear_history`) connect **directly**
to MongoDB via `pymongo` to seed/clear rows for test isolation, bypassing
the app entirely. Those specific tests need a real MongoDB reachable at
`MONGO_URL` — there's no mock substitute for them, since direct-DB state
control is exactly what they're doing. Everything else in the suite only
talks to the app over HTTP.
