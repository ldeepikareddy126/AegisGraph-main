"""Seed the two fixed QA users + long-lived sessions that the test suite
expects to already exist.

`tests/backend_test.py` and `tests/test_simulator.py` authenticate with the
hardcoded bearer tokens `tok_ext_qa` (external role) and `tok_legal_qa`
(legal role) via `Authorization: Bearer <token>`. Nothing in the app creates
those on its own — they have to be seeded directly into Mongo once before
running the suite against a live server. This script does that.

Usage (from the project root, backend venv active, backend/.env populated,
and MongoDB reachable):

    python scripts/seed_qa_fixtures.py

Safe to re-run — every write is an upsert.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

EXT_TOKEN = "tok_ext_qa"
LEGAL_TOKEN = "tok_legal_qa"

FIXTURES = [
    {
        "user_id": "user_qa_external",
        "email": "qa.external@example.com",
        "name": "QA External",
        "role": "external",
        "token": EXT_TOKEN,
    },
    {
        "user_id": "user_qa_legal",
        "email": "qa.legal@enron.com",
        "name": "QA Legal",
        "role": "legal",
        "token": LEGAL_TOKEN,
    },
]


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise SystemExit(
            "MONGO_URL / DB_NAME not set. Populate backend/.env first "
            "(see backend/.env.example)."
        )

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    now = datetime.now(timezone.utc)
    far_future = (now + timedelta(days=3650)).isoformat()

    for fx in FIXTURES:
        await db.users.update_one(
            {"user_id": fx["user_id"]},
            {
                "$set": {
                    "user_id": fx["user_id"],
                    "email": fx["email"],
                    "name": fx["name"],
                    "picture": None,
                    "role": fx["role"],
                    "linked_employee": None,
                    "department": None,
                    "created_at": now.isoformat(),
                }
            },
            upsert=True,
        )
        await db.user_sessions.update_one(
            {"session_token": fx["token"]},
            {
                "$set": {
                    "user_id": fx["user_id"],
                    "session_token": fx["token"],
                    "expires_at": far_future,
                    "created_at": now.isoformat(),
                }
            },
            upsert=True,
        )
        print(f"Seeded {fx['role']:>8} QA user ({fx['email']}) -> token={fx['token']}")

    client.close()
    print("Done. You can now run: pytest tests/ -n 0")


if __name__ == "__main__":
    asyncio.run(main())
