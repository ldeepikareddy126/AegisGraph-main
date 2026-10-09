"""AegisGraph FastAPI backend."""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Cookie, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import AutoReconnect, ServerSelectionTimeoutError
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from aegis.demo_data import employee_by_email
from aegis.disclosure import disclosure_decision
from aegis.kg_retrieval import Neo4jRetriever, Neo4jUnavailableError, retrieve
from aegis.llm import generate_answer
from aegis.safe_aggregates import (
    append_employee_aggregate,
    requests_employee_aggregate,
)
from aegis.moderation import (
    apply_moderation,
    disclose_retrieval,
    sanitize_high_answer,
    sanitize_medium_answer,
)
from aegis.risk_engine import ROLE_PROFILES, compute_risk, detect_entities
from aegis.simulator import SCENARIOS, by_id as simulator_by_id, evaluate as simulator_evaluate

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="AegisGraph")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aegis")

_NEO4J: Dict[str, Neo4jRetriever] = {}
_NEO4J_DEFAULT: Optional[Neo4jRetriever] = None

VALID_ROLES = list(ROLE_PROFILES.keys())
SIMULATOR_ROLES = {"admin", "legal", "executive"}
SELF_ASSIGNABLE_ROLES = {"external", "employee"}


def _neo4j_graph_is_usable(verification: Dict[str, Any]) -> bool:
    return all(
        verification.get(key, 0) > 0
        for key in ("node_count", "person_count", "email_count")
    )


def _connect_global_neo4j() -> tuple[Optional[Neo4jRetriever], Dict[str, Any]]:
    """Return a live, populated global driver, reconnecting after Neo4j restarts."""
    global _NEO4J_DEFAULT
    if _NEO4J_DEFAULT is not None:
        try:
            verification = _NEO4J_DEFAULT.verify()
            if _neo4j_graph_is_usable(verification):
                return _NEO4J_DEFAULT, verification
        except Exception:
            pass
        _NEO4J_DEFAULT.close()
        _NEO4J_DEFAULT = None

    uri = os.environ.get("NEO4J_URI")
    neo4j_user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if not (uri and neo4j_user and password):
        return None, {}

    candidate = Neo4jRetriever(uri, neo4j_user, password, os.environ.get("NEO4J_DATABASE"))
    try:
        verification = candidate.verify()
    except Exception:
        candidate.close()
        return None, {}
    if not _neo4j_graph_is_usable(verification):
        candidate.close()
        return None, verification
    _NEO4J_DEFAULT = candidate
    return candidate, verification


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

def _default_role_for(email: str) -> str:
    """Auto-classify newly signed-in users.

    Verified addresses in AEGIS_ADMIN_EMAILS receive the administrator role.
    Any address ending in @enron.com is treated as an internal employee;
    everything else is external. Users may change between the non-privileged
    risk profiles; other privileged roles remain administrator-assigned.
    """
    normalized_email = email.strip().casefold() if email else ""
    admin_emails = {
        configured.strip().casefold()
        for configured in os.environ.get("AEGIS_ADMIN_EMAILS", "").split(",")
        if configured.strip()
    }
    if normalized_email in admin_emails:
        return "admin"
    if email and email.lower().endswith("@enron.com"):
        return "employee"
    return "external"


async def get_current_user(request: Request,
                           session_token: Optional[str] = Cookie(default=None),
                           authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    token = session_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        doc = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    except (AutoReconnect, ServerSelectionTimeoutError) as ex:
        log.error("MongoDB session lookup failed: %s", ex)
        raise HTTPException(
            status_code=503,
            detail="Authentication service is temporarily unavailable. Verify MongoDB is running and retry.",
        ) from ex
    if not doc:
        raise HTTPException(status_code=401, detail="Session not found")
    exp = doc["expires_at"]
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")
    try:
        user = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    except (AutoReconnect, ServerSelectionTimeoutError) as ex:
        log.error("MongoDB user lookup failed: %s", ex)
        raise HTTPException(
            status_code=503,
            detail="Authentication service is temporarily unavailable. Verify MongoDB is running and retry.",
        ) from ex
    if not user:
        raise HTTPException(status_code=401, detail="User missing")
    user["_session_id"] = doc.get("session_id") or hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()
    legacy_role = user.get("role")
    if legacy_role in {"analyst", "manager"}:
        user["role"] = "employee"
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"role": "employee"}},
        )
    return user


class GoogleAuthBody(BaseModel):
    credential: str  # Google ID token (JWT) from Google Identity Services


@api.post("/auth/google")
async def auth_google(body: GoogleAuthBody, response: Response):
    """Verify a Google ID token and establish a session.

    Uses Google's tokeninfo endpoint so we don't need a client secret. The
    id_token's `aud` MUST match GOOGLE_OAUTH_CLIENT_ID.
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_OAUTH_CLIENT_ID not configured")
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": body.credential},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google credential")
    data = r.json()
    if data.get("aud") != client_id:
        raise HTTPException(status_code=401, detail="Token audience mismatch")
    if data.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(status_code=401, detail="Bad token issuer")
    if not data.get("email_verified") in (True, "true"):
        raise HTTPException(status_code=401, detail="Email not verified")
    email = data["email"]
    # Normalise the fields we later store to match what the rest of the code expects.
    data = {
        "email": email,
        "name": data.get("name") or email.split("@")[0],
        "picture": data.get("picture"),
    }
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        role = (
            "admin"
            if _default_role_for(email) == "admin"
            else existing.get("role") or _default_role_for(email)
        )
        await db.users.update_one({"user_id": user_id}, {"$set": {
            "name": data.get("name"),
            "picture": data.get("picture"),
            "role": role,
        }})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        role = _default_role_for(email)
        emp = employee_by_email(email) or {}
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": data.get("name"),
            "picture": data.get("picture"),
            "role": role,
            "linked_employee": emp.get("id"),
            "department": emp.get("department"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    token = uuid.uuid4().hex + uuid.uuid4().hex  # 64-char opaque session token
    session_id = uuid.uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_id": session_id,
        "session_token": token,
        "expires_at": expires.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    response.set_cookie(
        key="session_token", value=token, path="/",
        httponly=True, secure=(os.environ.get("AEGIS_COOKIE_INSECURE") != "1"), samesite=("lax" if os.environ.get("AEGIS_COOKIE_INSECURE") == "1" else "none"),
        max_age=7 * 24 * 60 * 60,
    )
    return {"user_id": user_id, "email": email,
            "name": data.get("name"), "picture": data.get("picture"),
            "role": role}


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {k: user.get(k) for k in
            ("user_id", "email", "name", "picture", "role",
             "linked_employee", "department")}


@api.get("/auth/me")
async def auth_me(request: Request,
                  session_token: Optional[str] = Cookie(default=None),
                  authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    return _public_user(user)


@api.post("/auth/logout")
async def auth_logout(response: Response,
                      session_token: Optional[str] = Cookie(default=None)):
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


class RoleBody(BaseModel):
    role: str


@api.put("/me/role")
async def update_role(body: RoleBody, request: Request,
                      session_token: Optional[str] = Cookie(default=None),
                      authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400,
                            detail=f"Invalid role. Must be one of {VALID_ROLES}")
    current_role = user.get("role", "external")
    if body.role in SIMULATOR_ROLES and current_role not in SIMULATOR_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Privileged roles must be assigned by an administrator.",
        )
    await db.users.update_one({"user_id": user["user_id"]},
                              {"$set": {"role": body.role}})
    user["role"] = body.role
    return _public_user(user)


@api.get("/roles")
async def list_roles():
    return {
        "roles": [
            {"id": rid, "label": p["label"],
             "clearance": p["clearance"], "risk_adjustment": p["bump"]}
            for rid, p in ROLE_PROFILES.items()
        ]
    }


# --------------------------------------------------------------------------
# Neo4j
# --------------------------------------------------------------------------

class Neo4jCreds(BaseModel):
    uri: str = Field(..., description="bolt://host:7687")
    user: str
    password: str
    database: Optional[str] = Field(
        default=None, description="Neo4j database name; omit to use the server default"
    )


@api.post("/neo4j/test")
async def neo4j_test(body: Neo4jCreds, request: Request,
                     session_token: Optional[str] = Cookie(default=None),
                     authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    try:
        rr = Neo4jRetriever(body.uri, body.user, body.password, body.database)
        rr.verify()
    except Exception as e:
        return {"ok": False, "error": f"Could not connect: {e}. "
                                       "Verify Neo4j Desktop is running, "
                                       "the bolt port is exposed, and the "
                                       "credentials are correct."}
    old = _NEO4J.pop(user["user_id"], None)
    if old:
        old.close()
    _NEO4J[user["user_id"]] = rr
    await db.users.update_one({"user_id": user["user_id"]},
                              {"$set": {"neo4j_uri": body.uri,
                                        "neo4j_user": body.user,
                                        "neo4j_database": body.database}})
    return {"ok": True, "database": body.database}


@api.post("/neo4j/disconnect")
async def neo4j_disconnect(request: Request,
                           session_token: Optional[str] = Cookie(default=None),
                           authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    old = _NEO4J.pop(user["user_id"], None)
    if old:
        old.close()
    return {"ok": True}


@api.get("/neo4j/status")
async def neo4j_status(request: Request,
                       session_token: Optional[str] = Cookie(default=None),
                       authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    user_override = user["user_id"] in _NEO4J
    if user_override:
        active_driver = _NEO4J[user["user_id"]]
        try:
            verification = active_driver.verify()
        except Exception:
            verification = {}
    else:
        active_driver, verification = _connect_global_neo4j()
    connected = False
    if active_driver is not None:
        connected = _neo4j_graph_is_usable(verification)
    if connected and active_driver is not None:
        try:
            semantic_search = active_driver.semantic_index_status()
        except Exception as ex:
            log.warning("Semantic retrieval status unavailable: %s", ex)
            semantic_search = {
                "ready": False,
                "index_ready": False,
                "model_available": False,
                "model_error": "Semantic retrieval status could not be checked.",
                "model": os.environ.get(
                    "AEGIS_EMBEDDING_MODEL", "all-MiniLM-L6-v2"
                ),
            }
    else:
        semantic_search = {
            "ready": False,
            "index_ready": False,
            "model_available": False,
            "model_error": None,
            "model": os.environ.get(
                "AEGIS_EMBEDDING_MODEL", "all-MiniLM-L6-v2"
            ),
        }
    return {"connected": connected,
            "mode": "neo4j" if connected else "unavailable",
            "status": "connected" if connected else "unavailable",
            "global_default": _NEO4J_DEFAULT is not None,
            "database": getattr(active_driver, "database", None),
            "verification": verification,
            "semantic_search": semantic_search}



# --------------------------------------------------------------------------
# Query pipeline
# --------------------------------------------------------------------------

class QueryBody(BaseModel):
    query: str


def _is_privileged(user: Dict[str, Any]) -> bool:
    return (user.get("role") or "external") in SIMULATOR_ROLES


async def _run_pipeline(user: Dict[str, Any], q: str,
                        source_tag: str = "user",
                        role_override: Optional[str] = None,
                        persist: bool = True,
                        behavior_history: Optional[bool] = None) -> Dict[str, Any]:
    """Execute the full retrieval → risk → moderation → LLM pipeline.

    Shared between the standard `/api/query` endpoint and the simulator so
    behaviour is guaranteed to match byte-for-byte.

    When ``role_override`` is set, that role is used for risk scoring instead
    of the authenticated user's role — this powers the Compare View.  When
    ``persist=False`` the run is not written to history and does not consume
    or update the user's EWMA context, so multiple runs of the same query
    across roles are directly comparable.
    """
    global _NEO4J_DEFAULT
    t0 = time.time()
    request_time = t0
    request_datetime = datetime.fromtimestamp(request_time, tz=timezone.utc)
    request_timestamp = request_datetime.isoformat()
    effective_role = role_override or user.get("role", "external")
    if behavior_history is None:
        behavior_history = persist
    session_id = user.get("_session_id") or hashlib.sha256(
        user["user_id"].encode("utf-8")
    ).hexdigest()
    if behavior_history:
        history_filter = {
            "user_id": user["user_id"],
            "session_id": session_id,
            "origin": {"$not": {"$regex": "^simulator:"}},
        }
        prev = await db.query_history.find(
            history_filter,
            {"_id": 0, "ewma": 1, "created_at": 1, "requested_at": 1,
             "query": 1, "entities": 1},
        ).sort("created_at", -1).to_list(20)
        prev_ewma = prev[0]["ewma"] if prev else None
        session_queries = [
            p["query"] for p in reversed(prev)
            if isinstance(p.get("query"), str)
        ]
        prior_entities = []
        for item in prev:
            if isinstance(item.get("entities"), list):
                prior_entities.extend(item["entities"])
            elif isinstance(item.get("query"), str):
                prior_entities.extend(detect_entities(item["query"]))
        cutoff_timestamp = (
            request_datetime - timedelta(seconds=60)
        ).isoformat()
        recent_query_count = await db.query_history.count_documents({
            **history_filter,
            "$or": [
                {"requested_at": {"$gte": cutoff_timestamp,
                                  "$lte": request_timestamp}},
                {
                    "requested_at": {"$exists": False},
                    "created_at": {"$gte": cutoff_timestamp,
                                   "$lte": request_timestamp},
                },
            ],
        })
    else:
        prev_ewma = None
        session_queries = []
        prior_entities = []
        recent_query_count = 0

    driver = _NEO4J.get(user["user_id"])
    verification = None
    if driver is None:
        driver, verification = _connect_global_neo4j()
    r_t0 = time.time()
    if driver is None:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is unavailable. Start the configured Neo4j database and use Connect Neo4j, then retry.",
        )
    try:
        if verification is None:
            verification = driver.verify()
        if not _neo4j_graph_is_usable(verification):
            raise Neo4jUnavailableError(
                "Neo4j is reachable but the configured database has no usable Person/Email graph."
            )
        retrieved = retrieve(q, neo4j=driver, top_k=8)
    except Neo4jUnavailableError as ex:
        raise HTTPException(status_code=503, detail=str(ex)) from ex
    except Exception as ex:
        if driver is _NEO4J_DEFAULT:
            driver.close()
            _NEO4J_DEFAULT = None
        raise HTTPException(
            status_code=503,
            detail=f"Neo4j query could not be completed: {ex}. Verify the database is online and retry.",
        ) from ex
    retrieval_ms = int((time.time() - r_t0) * 1000)

    risk = compute_risk(
        q,
        recent_query_times=[],
        retrieved_emails=len(retrieved["matched_emails"]),
        hop_depth=2,
        prev_ewma=prev_ewma,
        user_role=effective_role,
        session_queries=session_queries,
        session_entities=prior_entities,
        recent_query_count=recent_query_count,
        request_time=request_time,
    )

    disclosure = disclosure_decision(q, risk["level"])
    employee_count = None
    if disclosure["level"] != "HIGH" and requests_employee_aggregate(q):
        try:
            employee_count = driver.employee_count()
        except Exception as ex:
            log.exception("Could not retrieve the requested employee aggregate.")
            raise HTTPException(
                status_code=503,
                detail=(
                    "The configured graph could not provide a classified "
                    "employee-record count. Verify its employee classification "
                    "data and retry."
                ),
            ) from ex

    moderation = apply_moderation(
        retrieved["matched_emails"],
        disclosure["level"],
        disclosure_reason=disclosure["reason"],
    )
    public_retrieval = disclose_retrieval(
        retrieved, moderation, disclosure["level"]
    )

    ai = await generate_answer(
        query=q,
        moderated_context=moderation["context"],
        risk_level=disclosure["level"],
        moderation_explanation=moderation["explanation"],
        topic_hint=moderation.get("topic_hint"),
        session_id=f"aegis-{user['user_id']}",
        safe_facts=(
            [f"The configured graph marks {employee_count} distinct employee records."]
            if employee_count is not None
            else None
        ),
    )
    if disclosure["level"] == "HIGH":
        ai = sanitize_high_answer(ai, records_provided=len(moderation["context"]))
    elif disclosure["level"] == "MEDIUM":
        ai = sanitize_medium_answer(ai, records_provided=len(moderation["context"]))
    if employee_count is not None:
        ai = append_employee_aggregate(
            ai, employee_count, disclosure["level"]
        )

    total_ms = int((time.time() - t0) * 1000)
    query_id = f"q_{uuid.uuid4().hex[:12]}"
    doc = {
        "query_id": query_id,
        "user_id": user["user_id"],
        "user_email": user.get("email"),
        "query": q,
        "origin": source_tag,
        "risk_level": risk["level"],
        "disclosure_level": disclosure["level"],
        "disclosure_gate": disclosure["reason"],
        "ewma": risk["ewma"],
        "adjusted": risk["adjusted"],
        "composite": risk["composite"],
        "corroboration": risk["corroboration"],
        "fused": risk["fused"],
        "role_adjusted": risk["role_adjusted"],
        "hard_gate": risk["hard_gate"],
        "hard_gate_reason": risk["hard_gate_reason"],
        "signals": risk["signals"],
        "weights": risk["weights"],
        "reasoning": risk["reasoning"],
        "role": risk["role"],
        "role_adjustment": risk["role_adjustment"],
        "moderation_explanation": moderation["explanation"],
        "k_eff": moderation["k_eff"],
        "matched_emails_count": public_retrieval["count"],
        "source": retrieved["source"],
        "summary": ai["summary"],
        "confidence": ai.get("confidence", 0.7),
        "latency_ms": total_ms,
        "retrieval_ms": retrieval_ms,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "requested_at": request_timestamp,
        "session_id": session_id,
        "entities": risk["entities"],
    }
    if persist:
        await db.query_history.insert_one(doc)

    return {
        "query_id": query_id,
        "query": q,
        "risk": {
            "level": risk["level"],
            "behavioral_level": risk["level"],
            "score": risk["adjusted"],
            "raw_ewma": risk["ewma"],
            "composite": risk["composite"],
            "signals": risk["signals"],
            "weights": risk["weights"],
            "reasoning": risk["reasoning"],
            "sensitive_terms": risk["sensitive_terms"],
            "entities": risk["entities"],
            "role": risk["role"],
            "role_label": risk["role_label"],
            "role_adjustment": risk["role_adjustment"],
            "corroboration": risk["corroboration"],
            "fused": risk["fused"],
            "role_adjusted": risk["role_adjusted"],
            "hard_gate": risk["hard_gate"],
            "hard_gate_reason": risk["hard_gate_reason"],
        },
        "pipeline": [
            {"step": "Intent Detection",         "status": "done", "detail": f"parsed {len(q.split())} token(s)"},
            {
                "step": "Knowledge Graph Retrieval",
                "status": "done",
                "detail": (
                    f"{moderation['topic_hint']['record_count_bucket']} matching record(s); "
                    "individual details withheld"
                    if disclosure["level"] == "HIGH"
                    else f"{len(retrieved['matched_emails'])} matched; "
                         f"{public_retrieval['count']} disclosed at "
                         f"{disclosure['level']} via "
                         f"{public_retrieval['retrieval_mode']}"
                ),
            },
            {"step": "Privacy Risk Analysis",    "status": "done", "detail": f"score={risk['adjusted']:.2f} → {risk['level']} (role: {risk['role_label']})"},
            {"step": "Context Filtering",        "status": "done", "detail": f"k_eff={moderation['k_eff']} · redactions: {', '.join(moderation['redactions_applied']) or 'none'}"},
            {
                "step": "AI Response Generation",
                "status": "done",
                "detail": (
                    "high-risk response sanitized · "
                    f"{ai.get('provider', 'unknown')} / {ai.get('model', 'unknown')}"
                    if disclosure["level"] == "HIGH"
                    else (
                        f"deterministic fallback ({ai.get('fallback_reason', 'unavailable')})"
                        if ai.get("fallback")
                        else f"{ai.get('provider', 'LLM')} / {ai.get('model', 'configured model')}"
                    )
                ),
            },
            {"step": "Final Moderated Response", "status": "done", "detail": moderation["explanation"]},
        ],
        "moderation": moderation,
        "disclosure": disclosure,
        "answer": ai,
        "retrieved": {
            **{key: value for key, value in public_retrieval.items() if key != "graph"},
        },
        "graph": public_retrieval["graph"],
        "latency_ms": total_ms,
        "retrieval_ms": retrieval_ms,
    }


@api.post("/query")
async def query(body: QueryBody, request: Request,
                session_token: Optional[str] = Cookie(default=None),
                authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    q = (body.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Query is empty.")
    if len(q) > 2000:
        raise HTTPException(status_code=400,
                            detail="Query is too long (2000 char max).")
    return await _run_pipeline(user, q, source_tag="user")


# --------------------------------------------------------------------------
# Attack simulator (role-gated)
# --------------------------------------------------------------------------

class SimulatorRunBody(BaseModel):
    scenario_id: str


def _require_simulator_access(user: Dict[str, Any]) -> None:
    if not _is_privileged(user):
        raise HTTPException(
            status_code=403,
            detail="Attack Simulator is restricted to Administrator, Legal, and Executive roles.",
        )


@api.get("/simulator/scenarios")
async def simulator_scenarios(request: Request,
                              session_token: Optional[str] = Cookie(default=None),
                              authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    _require_simulator_access(user)
    return {"scenarios": [
        {k: v for k, v in s.items() if k != "prompt"} | {"preview": s["prompt"][:120]}
        for s in SCENARIOS
    ]}


@api.post("/simulator/run")
async def simulator_run(body: SimulatorRunBody, request: Request,
                        session_token: Optional[str] = Cookie(default=None),
                        authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    _require_simulator_access(user)
    scenario = simulator_by_id(body.scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Unknown scenario")
    result = await _run_pipeline(user, scenario["prompt"],
                                 source_tag=f"simulator:{scenario['id']}",
                                 behavior_history=False)
    grade = simulator_evaluate(
        scenario, result["moderation"]["disclosure_level"]
    )
    result["scenario"] = {
        "id":                scenario["id"],
        "title":             scenario["title"],
        "category":          scenario["category"],
        "description":       scenario["description"],
        "severity":          scenario["severity"],
        "expected_level":    scenario["expected_level"],
        "expected_behavior": scenario["expected_behavior"],
    }
    result["evaluation"] = grade
    return result


@api.get("/simulator/access")
async def simulator_access(request: Request,
                           session_token: Optional[str] = Cookie(default=None),
                           authorization: Optional[str] = Header(default=None)):
    """Feature-flag probe used by the UI to decide whether to render the panel."""
    user = await get_current_user(request, session_token, authorization)
    return {"allowed": _is_privileged(user),
            "role": user.get("role"),
            "allowed_roles": sorted(SIMULATOR_ROLES)}


class SimulatorCompareBody(BaseModel):
    scenario_id: str
    roles: List[str] = Field(default_factory=lambda: ["external", "legal"])


@api.post("/simulator/compare")
async def simulator_compare(body: SimulatorCompareBody, request: Request,
                            session_token: Optional[str] = Cookie(default=None),
                            authorization: Optional[str] = Header(default=None)):
    """Run the same scenario for multiple roles side by side (no persistence)."""
    user = await get_current_user(request, session_token, authorization)
    _require_simulator_access(user)
    scenario = simulator_by_id(body.scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Unknown scenario")
    roles = body.roles or ["external", "legal"]
    invalid = [r for r in roles if r not in ROLE_PROFILES]
    if invalid:
        raise HTTPException(status_code=400,
                            detail=f"Unknown role(s): {invalid}")
    if len(roles) < 2:
        raise HTTPException(status_code=400,
                            detail="Provide at least two roles to compare")

    runs: List[Dict[str, Any]] = []
    for role in roles:
        result = await _run_pipeline(
            user, scenario["prompt"],
            source_tag=f"simulator:{scenario['id']}:compare",
            role_override=role,
            persist=False,
        )
        grade = simulator_evaluate(
            scenario, result["moderation"]["disclosure_level"]
        )
        runs.append({"role": role, "result": result, "evaluation": grade})

    return {
        "scenario": {
            "id":                scenario["id"],
            "title":             scenario["title"],
            "category":          scenario["category"],
            "description":       scenario["description"],
            "severity":          scenario["severity"],
            "expected_level":    scenario["expected_level"],
            "expected_behavior": scenario["expected_behavior"],
        },
        "runs": runs,
    }


# --------------------------------------------------------------------------
# History / analytics
# --------------------------------------------------------------------------

_HISTORY_FIELDS = ("query_id", "query", "risk_level", "disclosure_level",
                   "disclosure_gate", "ewma", "adjusted",
                   "role", "created_at", "summary", "confidence",
                   "latency_ms", "matched_emails_count", "source", "origin")

_HISTORY_PROJECTION = {
    "_id": 0,
    **{field: 1 for field in _HISTORY_FIELDS},
    "k_eff": 1,
}


def _safe_history_item(item: Dict[str, Any]) -> Dict[str, Any]:
    item["matched_emails_count"] = min(
        int(item.get("matched_emails_count") or 0),
        int(item.get("k_eff") or 0),
    )
    item.pop("k_eff", None)
    return item


@api.get("/history")
async def history(request: Request, limit: int = Query(default=100, ge=1, le=1000), search: str = "",
                  session_token: Optional[str] = Cookie(default=None),
                  authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    q: Dict[str, Any] = {"user_id": user["user_id"]}
    if search:
        q["query"] = {"$regex": re.escape(search[:200]), "$options": "i"}
    items = await db.query_history.find(q, _HISTORY_PROJECTION) \
        .sort("created_at", -1).to_list(limit)
    return {"items": [_safe_history_item(item) for item in items]}


@api.get("/history/export")
async def history_export(request: Request,
                         session_token: Optional[str] = Cookie(default=None),
                         authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    items = await db.query_history.find(
        {"user_id": user["user_id"]},
        _HISTORY_PROJECTION,
    ).sort("created_at", -1).to_list(1000)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(_HISTORY_FIELDS))
    writer.writeheader()
    for row in items:
        safe_row = _safe_history_item(row)
        writer.writerow({k: safe_row.get(k, "") for k in _HISTORY_FIELDS})
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="aegisgraph-history-{user["user_id"]}.csv"'},
    )


@api.get("/history/{query_id}")
async def history_item(query_id: str, request: Request,
                       session_token: Optional[str] = Cookie(default=None),
                       authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    doc = await db.query_history.find_one(
        {"query_id": query_id, "user_id": user["user_id"]},
        _HISTORY_PROJECTION,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return _safe_history_item(doc)


@api.get("/risk-trend")
async def risk_trend(request: Request, limit: int = Query(default=60, ge=1, le=500),
                     session_token: Optional[str] = Cookie(default=None),
                     authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    session_id = user.get("_session_id")
    items = await db.query_history.find(
        {"user_id": user["user_id"]},
        {"_id": 0, "ewma": 1, "adjusted": 1, "composite": 1,
         "signals": 1, "weights": 1, "reasoning": 1,
         "risk_level": 1, "disclosure_level": 1, "disclosure_gate": 1,
         "matched_emails_count": 1, "k_eff": 1, "hard_gate_reason": 1,
         "created_at": 1, "query": 1, "session_id": 1},
    ).sort("created_at", -1).to_list(limit)
    items.reverse()
    dist = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for it in items:
        dist[it["risk_level"]] = dist.get(it["risk_level"], 0) + 1
        it.setdefault("signals", {})
        it.setdefault("weights", {})
        it.setdefault("disclosure_level", it["risk_level"])
        it.setdefault("reasoning", "")
        effective_cap = int(it.pop("k_eff", 0) or 0)
        it["disclosed_records_count"] = min(
            int(it.pop("matched_emails_count", 0) or 0),
            effective_cap,
        )
        item_session_id = it.pop("session_id", None)
        it["current_session"] = bool(session_id and item_session_id == session_id)
    avg = round(sum(it.get("adjusted", it.get("ewma", 0)) for it in items) /
                max(1, len(items)), 3)
    current_session_count = (
        await db.query_history.count_documents({
            "user_id": user["user_id"],
            "session_id": session_id,
            "origin": {"$not": {"$regex": "^simulator:"}},
        })
        if session_id
        else 0
    )
    current_session_items = [it for it in items if it["current_session"]]
    latest_session_query = current_session_items[-1] if current_session_items else None
    return {"series": items, "distribution": dist,
            "count": len(items), "average_score": avg,
            "current_session": {
                "query_count": current_session_count,
                "latest_score": (
                    latest_session_query.get(
                        "adjusted", latest_session_query.get("ewma")
                    )
                    if latest_session_query
                    else None
                ),
                "latest_level": (
                    latest_session_query.get("risk_level")
                    if latest_session_query
                    else None
                ),
            }}


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")


@api.get("/admin/overview")
async def admin_overview(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await get_current_user(request, session_token, authorization)
    _require_admin(user)
    result = await db.query_history.aggregate([
        {
            "$facet": {
                "queries": [{
                    "$group": {
                        "_id": None,
                        "total": {"$sum": 1},
                        "average_score": {
                            "$avg": {"$ifNull": ["$adjusted", {"$ifNull": ["$ewma", 0]}]}
                        },
                        "latest_activity": {"$max": "$created_at"},
                        "low": {"$sum": {"$cond": [{"$eq": ["$risk_level", "LOW"]}, 1, 0]}},
                        "medium": {"$sum": {"$cond": [{"$eq": ["$risk_level", "MEDIUM"]}, 1, 0]}},
                        "high": {"$sum": {"$cond": [{"$eq": ["$risk_level", "HIGH"]}, 1, 0]}},
                        "disclosure_low": {"$sum": {"$cond": [{"$eq": ["$disclosure_level", "LOW"]}, 1, 0]}},
                        "disclosure_medium": {"$sum": {"$cond": [{"$eq": ["$disclosure_level", "MEDIUM"]}, 1, 0]}},
                        "disclosure_high": {"$sum": {"$cond": [{"$eq": ["$disclosure_level", "HIGH"]}, 1, 0]}},
                    }
                }],
                "accounts": [
                    {"$group": {"_id": "$user_id"}},
                    {"$count": "total"},
                ],
            }
        }
    ]).to_list(length=1)
    facets = result[0] if result else {}
    query_stats = (facets.get("queries") or [{}])[0]
    return {
        "accounts_with_history": (
            (facets.get("accounts") or [{}])[0].get("total", 0)
        ),
        "total_queries": query_stats.get("total", 0),
        "average_risk_score": round(query_stats.get("average_score") or 0, 3),
        "latest_activity": query_stats.get("latest_activity"),
        "risk_distribution": {
            "LOW": query_stats.get("low", 0),
            "MEDIUM": query_stats.get("medium", 0),
            "HIGH": query_stats.get("high", 0),
        },
        "disclosure_distribution": {
            "LOW": query_stats.get("disclosure_low", 0),
            "MEDIUM": query_stats.get("disclosure_medium", 0),
            "HIGH": query_stats.get("disclosure_high", 0),
        },
    }


@api.get("/admin/accounts")
async def admin_accounts(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000000),
    search: str = Query(default="", max_length=120),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await get_current_user(request, session_token, authorization)
    _require_admin(user)
    pipeline: List[Dict[str, Any]] = [
        {
            "$group": {
                "_id": "$user_id",
                "query_count": {"$sum": 1},
                "latest_activity": {"$max": "$created_at"},
                "average_risk_score": {
                    "$avg": {"$ifNull": ["$adjusted", {"$ifNull": ["$ewma", 0]}]}
                },
                "low": {"$sum": {"$cond": [{"$eq": ["$risk_level", "LOW"]}, 1, 0]}},
                "medium": {"$sum": {"$cond": [{"$eq": ["$risk_level", "MEDIUM"]}, 1, 0]}},
                "high": {"$sum": {"$cond": [{"$eq": ["$risk_level", "HIGH"]}, 1, 0]}},
            }
        },
        {
            "$lookup": {
                "from": "users",
                "localField": "_id",
                "foreignField": "user_id",
                "as": "account",
            }
        },
        {"$unwind": "$account"},
    ]
    if search.strip():
        escaped = re.escape(search.strip())
        pipeline.append({
            "$match": {
                "$or": [
                    {"account.email": {"$regex": escaped, "$options": "i"}},
                    {"account.name": {"$regex": escaped, "$options": "i"}},
                ]
            }
        })
    pipeline.extend([
        {
            "$facet": {
                "items": [
                    {"$sort": {"latest_activity": -1, "_id": 1}},
                    {"$skip": offset},
                    {"$limit": limit},
                    {
                        "$project": {
                            "_id": 0,
                            "user_id": "$_id",
                            "email": "$account.email",
                            "name": "$account.name",
                            "role": "$account.role",
                            "created_at": "$account.created_at",
                            "query_count": 1,
                            "latest_activity": 1,
                            "average_risk_score": 1,
                            "risk_distribution": {
                                "LOW": "$low",
                                "MEDIUM": "$medium",
                                "HIGH": "$high",
                            },
                        }
                    },
                ],
                "meta": [{"$count": "total"}],
            }
        }
    ])
    result = await db.query_history.aggregate(pipeline).to_list(length=1)
    facets = result[0] if result else {}
    return {
        "items": facets.get("items", []),
        "total": (facets.get("meta") or [{}])[0].get("total", 0),
        "limit": limit,
        "offset": offset,
    }


@api.get("/admin/accounts/{user_id}/history")
async def admin_account_history(
    user_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000000),
    search: str = Query(default="", max_length=120),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    admin_user = await get_current_user(request, session_token, authorization)
    _require_admin(admin_user)
    account = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1, "role": 1, "created_at": 1},
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    query_filter: Dict[str, Any] = {"user_id": user_id}
    if search.strip():
        query_filter["query"] = {
            "$regex": re.escape(search.strip()),
            "$options": "i",
        }
    projection = {
        "_id": 0,
        "query_id": 1,
        "query": 1,
        "risk_level": 1,
        "disclosure_level": 1,
        "disclosure_gate": 1,
        "ewma": 1,
        "adjusted": 1,
        "composite": 1,
        "signals": 1,
        "weights": 1,
        "reasoning": 1,
        "hard_gate_reason": 1,
        "role": 1,
        "summary": 1,
        "confidence": 1,
        "latency_ms": 1,
        "retrieval_ms": 1,
        "matched_emails_count": 1,
        "k_eff": 1,
        "source": 1,
        "origin": 1,
        "created_at": 1,
    }
    total = await db.query_history.count_documents(query_filter)
    records = await db.query_history.find(query_filter, projection).sort(
        "created_at", -1
    ).skip(offset).limit(limit).to_list(length=limit)
    safe_records = []
    for record in records:
        effective_cap = int(record.pop("k_eff", 0) or 0)
        record["disclosed_records_count"] = min(
            int(record.pop("matched_emails_count", 0) or 0),
            effective_cap,
        )
        safe_records.append(record)
    return {
        "account": account,
        "items": safe_records,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------

@api.get("/health")
async def health():
    mongo_connected = True
    try:
        await db.command("ping")
    except (AutoReconnect, ServerSelectionTimeoutError) as ex:
        log.warning("MongoDB health check failed: %s", ex)
        mongo_connected = False
    return {
        "ok": mongo_connected,
        "llm": bool(os.environ.get("OPENAI_API_KEY")),
        "mongo": {"connected": mongo_connected},
        "retrieval": {"mode": "neo4j-only"},
    }


@api.get("/")
async def root():
    return {"service": "aegisgraph", "ok": True}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    global _NEO4J_DEFAULT
    if _NEO4J_DEFAULT:
        _NEO4J_DEFAULT.close()
        _NEO4J_DEFAULT = None
    uri = os.environ.get("NEO4J_URI")
    neo4j_user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if uri and neo4j_user and password:
        try:
            _NEO4J_DEFAULT = Neo4jRetriever(
                uri, neo4j_user, password, os.environ.get("NEO4J_DATABASE")
            )
            _NEO4J_DEFAULT.verify()
            log.info("Global Neo4j retriever connected")
        except Exception as ex:
            log.warning(f"Global Neo4j connection unavailable: {ex}")
            if _NEO4J_DEFAULT:
                _NEO4J_DEFAULT.close()
            _NEO4J_DEFAULT = None


@app.on_event("shutdown")
async def _shutdown():
    global _NEO4J_DEFAULT
    for r in _NEO4J.values():
        r.close()
    _NEO4J.clear()
    if _NEO4J_DEFAULT:
        _NEO4J_DEFAULT.close()
        _NEO4J_DEFAULT = None
    client.close()
