"""Synthetic Enron-style support data retained for profile and redaction logic.

The deterministic generator can still produce synthetic fixtures for tools
and tests, but this module is not a retrieval backend and its corpus is never
used as a substitute when Neo4j is unavailable.

Content is templated but seeded so re-imports are reproducible and every
foreign-key reference (sender, recipients, department) stays consistent.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from typing import Any, Dict, List

# --------------------------------------------------------------------------
# Employees – stable IDs, realistic Enron identities, department + clearance
# --------------------------------------------------------------------------

_EMPLOYEE_DEFS = [
    # Executive
    ("Jeffrey Skilling",   "Executive",       4),
    ("Kenneth Lay",        "Executive",       4),
    ("Greg Whalley",       "Executive",       4),
    ("Mark Frevert",       "Executive",       4),
    # Finance
    ("Andrew Fastow",      "Finance",         4),
    ("Ben Glisan",         "Finance",         3),
    ("Michael Kopper",     "Finance",         3),
    ("Rick Causey",        "Finance",         3),
    # Legal
    ("Sara Shackleton",    "Legal",           3),
    ("Richard Sanders",    "Legal",           3),
    ("Kay Mann",           "Legal",           2),
    ("Mark Taylor",        "Legal",           2),
    ("Michelle Cash",      "Legal",           2),
    # Trading – West Power
    ("Tim Belden",         "West Power",      3),
    ("John Forney",        "West Power",      2),
    ("Chris Calger",       "West Power",      2),
    # Trading – East / gas
    ("John Lavorato",      "Trading",         3),
    ("Louise Kitchen",     "Trading",         3),
    ("Kevin Presto",       "Trading",         2),
    ("Phillip Allen",      "Trading",         2),
    # Research
    ("Vince Kaminski",     "Research",        3),
    ("Stinson Gibner",     "Research",        2),
    ("Grant Masson",       "Research",        2),
    # Public affairs
    ("Steven Kean",        "Public Affairs",  3),
    ("Karen Denne",        "Public Affairs",  2),
    ("Mark Palmer",        "Public Affairs",  2),
    # Broadband
    ("Kenneth Rice",       "Broadband",       3),
    ("Kevin Hannon",       "Broadband",       3),
    # HR
    ("Cindy Olson",        "HR",              3),
    # International
    ("Rebecca Mark",       "International",   4),
    ("Wade Cline",         "International",   2),
]

def _emp_email(name: str) -> str:
    first, last = name.lower().split(" ", 1)
    return f"{first[0]}.{last.replace(' ', '')}@enron.com"

def _emp_id(name: str) -> str:
    return "e_" + hashlib.md5(name.encode()).hexdigest()[:10]

EMPLOYEES: List[Dict[str, Any]] = [
    {
        "id": _emp_id(name),
        "name": name,
        "email": _emp_email(name),
        "department": dept,
        "clearance": clearance,
    }
    for name, dept, clearance in _EMPLOYEE_DEFS
]

_BY_DEPT: Dict[str, List[Dict[str, Any]]] = {}
for e in EMPLOYEES:
    _BY_DEPT.setdefault(e["department"], []).append(e)
_BY_ID = {e["id"]: e for e in EMPLOYEES}
_BY_NAME = {e["name"]: e for e in EMPLOYEES}

# --------------------------------------------------------------------------
# Topic / template library
# --------------------------------------------------------------------------

TOPIC_KEYWORDS = {
    "california energy": ["california", "iso", "west power", "energy crisis",
                          "intertie", "ferc", "cal-iso", "outage", "ancillary",
                          "davis", "sacramento", "path-15", "wholesale"],
    "trading":           ["trading", "trader", "desk", "position", "hedge",
                          "p&l", "book", "spread", "spark spread", "basis"],
    "trading strategy":  ["fat boy", "death star", "get shorty", "ricochet",
                          "load shift", "megawatt laundering"],
    "finance":           ["finance", "spe", "ljm", "raptor", "chewco",
                          "accounting", "balance sheet", "restatement",
                          "consolidation", "footnote", "10-Q", "10-K"],
    "legal":             ["legal", "counsel", "isda", "eei", "master agreement",
                          "contract", "subpoena", "regulatory", "hold notice"],
    "hr":                ["hr", "bonus", "termination", "compensation",
                          "severance", "employee", "salary", "raise", "rif",
                          "performance review", "prc"],
    "research":          ["research", "model", "analytics", "forecast",
                          "backtest", "monte carlo", "value at risk", "var"],
    "public affairs":    ["public", "press", "analyst", "hearing", "release",
                          "communication", "media", "op-ed"],
    "broadband":         ["broadband", "eBS", "video on demand", "bandwidth",
                          "blockbuster", "intermediation"],
    "retail energy":     ["retail energy", "eesi", "small commercial",
                          "residential", "customer acquisition"],
    "international":     ["dabhol", "india", "argentina", "elektro",
                          "wessex", "azurix"],
    "weather":           ["weather derivative", "hdd", "cdd", "temperature",
                          "seasonal"],
    "eol":               ["enron online", "eol", "platform", "trading platform",
                          "netco"],
    "confidential":      ["confidential", "sensitive", "restricted", "private",
                          "eyes only", "attorney-client"],
}

# ~30 templates for realistic email bodies (subject, body, topic, dept, ...).
_TEMPLATES: List[Dict[str, Any]] = [
    # California trading operations
    {"dept_from": "West Power", "dept_to": ["Trading", "Research"],
     "topic": ["california energy", "trading"],
     "subject": "West Power desk – California ISO clearing prices HE {he}",
     "body": "Team, our position on the California ISO shows unusual clearing prices during HE {he}. Path-15 congestion widened by ${cong}/MWh; we rotated {mw}MW into mid-C. Please confirm hedges before market open."},
    {"dept_from": "West Power", "dept_to": ["Trading", "Legal"],
     "topic": ["california energy", "trading strategy", "confidential"],
     "subject": "Reminder: internal strategy names in email",
     "body": "Please avoid using internal names such as Death Star, Fat Boy, Get Shorty or Ricochet in written correspondence. Legal has asked that arbitrage tactics be discussed in meetings only."},
    {"dept_from": "West Power", "dept_to": ["Trading"],
     "topic": ["california energy", "trading"],
     "subject": "Ancillary services bids – {region} zone",
     "body": "The {region} zone showed unusual dispatch behaviour overnight. Ancillary bids cleared {pct}% above forecast. Model was recalibrated at 04:30."},
    # LJM/SPE finance
    {"dept_from": "Finance", "dept_to": ["Legal", "Executive"],
     "topic": ["finance", "confidential"],
     "subject": "Confidential – LJM{n} SPE structuring memo",
     "body": "The LJM{n} documentation is highly confidential. Originals in the secure room. Consolidation footnote in the 10-Q remains open pending Arthur Andersen sign-off."},
    {"dept_from": "Finance", "dept_to": ["Executive"],
     "topic": ["finance", "confidential"],
     "subject": "Raptor {n} – mark-to-market recognition",
     "body": "Raptor {n} realised gains of ${amt}M this period; hedge counterparty capacity is approaching internal caps. Recommend engaging outside counsel before extending."},
    {"dept_from": "Finance", "dept_to": ["Executive", "Legal"],
     "topic": ["finance", "confidential"],
     "subject": "Q{q} close – off-balance-sheet positions",
     "body": "Preliminary numbers for Q{q}. Some SPE items remain sensitive; happy to walk through in person. Consolidation exposure is estimated at ${amt}M."},
    # Legal
    {"dept_from": "Legal", "dept_to": ["Executive", "Legal"],
     "topic": ["legal", "confidential"],
     "subject": "FERC subpoena – document retention hold",
     "body": "We received a document request from FERC regarding West Power activity. Preserve all correspondence involving Tim Belden and West Power trading, dated 2000–2001. Do not delete or auto-archive."},
    {"dept_from": "Legal", "dept_to": ["Legal", "Trading"],
     "topic": ["legal"],
     "subject": "ISDA master – updated netting language",
     "body": "Attached is the revised ISDA master with the new netting language and cross-default trigger. Counterparties {cp1} and {cp2} are next in the queue."},
    {"dept_from": "Legal", "dept_to": ["Executive"],
     "topic": ["legal", "confidential"],
     "subject": "Attorney-client privileged – Sherron Watkins memo",
     "body": "The referenced memo is attorney-client privileged. Distribution is limited to counsel and named recipients. Please store in the secure repository only."},
    # HR / compensation
    {"dept_from": "HR", "dept_to": ["Executive", "HR"],
     "topic": ["hr", "confidential"],
     "subject": "{year} mid-year bonus pool – trader compensation",
     "body": "Attached is the proposed bonus pool. Please keep confidential; individual amounts and SSNs are on tab 2. Contact my desk 713-853-{ext} if you need to discuss."},
    {"dept_from": "HR", "dept_to": ["Legal", "HR"],
     "topic": ["hr", "legal", "confidential"],
     "subject": "Confidential – planned RIF cohort {cohort}",
     "body": "The list of employees planned for RIF cohort {cohort} is confidential. Severance amounts and personal identifiers must not leave HR/Legal."},
    {"dept_from": "HR", "dept_to": ["Executive"],
     "topic": ["hr"],
     "subject": "PRC (Performance Review Committee) calibration – {group}",
     "body": "Calibration session for {group} concluded. {a}% at Superior, {b}% Excellent, {c}% Strong. Detailed ratings attached."},
    # Research
    {"dept_from": "Research", "dept_to": ["Trading", "Executive"],
     "topic": ["research", "trading"],
     "subject": "Model validation – {desk} price forecasting",
     "body": "The stochastic volatility model backtests within {pct}% of realized prices for {desk}. Value-at-Risk 1-day 95% at ${var}M. Recommend production rollout."},
    {"dept_from": "Research", "dept_to": ["Trading"],
     "topic": ["research", "weather"],
     "subject": "Weather derivatives book – {season} HDD/CDD outlook",
     "body": "Weather book is diversified. HDD exposure in {region} peaks at {hdd}; recommend adding CDD hedge for cooling season."},
    # Public affairs
    {"dept_from": "Public Affairs", "dept_to": ["Executive"],
     "topic": ["public affairs", "california energy"],
     "subject": "External comms – {topic_ext}",
     "body": "Drafted talking points for {topic_ext}. Emphasize supply constraints and grid reliability. Avoid discussing specific trading strategies or ISO market design."},
    {"dept_from": "Public Affairs", "dept_to": ["Executive", "Public Affairs"],
     "topic": ["public affairs"],
     "subject": "Analyst call preparation – Q{q}",
     "body": "Top three expected analyst questions: (1) EPS guidance, (2) SPE restructurings, (3) broadband commercialisation. Prep book attached."},
    # Broadband
    {"dept_from": "Broadband", "dept_to": ["Executive"],
     "topic": ["broadband"],
     "subject": "Enron Broadband – video on demand pilot",
     "body": "Blockbuster VOD pilot streamed {tb}TB last week to {cities} cities. Bandwidth costs above plan; commercial launch pushed to Q{q}."},
    # Retail
    {"dept_from": "Trading", "dept_to": ["Executive"],
     "topic": ["retail energy"],
     "subject": "EESI – small commercial customer acquisition",
     "body": "Retail Energy Services signed {n} new small commercial customers this month. Acquisition cost trending down to ${cost} per account."},
    # International
    {"dept_from": "International", "dept_to": ["Executive", "Legal"],
     "topic": ["international"],
     "subject": "Dabhol – MSEB payment status",
     "body": "MSEB missed the {month} invoice; total outstanding is now ${amt}M. Preparing to trigger the government of Maharashtra counter-guarantee."},
    # EOL / platform
    {"dept_from": "Trading", "dept_to": ["Executive"],
     "topic": ["eol"],
     "subject": "Enron Online – daily volume record",
     "body": "EOL hit a new daily notional volume record of ${amt}B, {n} transactions across {products} products."},
    # Executive all-hands
    {"dept_from": "Executive", "dept_to": ["Executive", "Public Affairs"],
     "topic": ["public affairs"],
     "subject": "All-employee memo – strategic direction",
     "body": "As we close out Q{q}, our priorities remain the wholesale trading platform, broadband commercialisation, and disciplined capital allocation. Thank you for another strong quarter."},
]

# --------------------------------------------------------------------------
# Generator
# --------------------------------------------------------------------------

_START = date(2000, 6, 1)
_DAYS = 540  # through late 2001


def _pick_sender(dept: str, rng: random.Random) -> Dict[str, Any]:
    pool = _BY_DEPT.get(dept) or EMPLOYEES
    return rng.choice(pool)


def _pick_recipients(depts: List[str], sender_id: str, rng: random.Random) -> List[Dict[str, Any]]:
    pool = []
    for d in depts:
        pool.extend(_BY_DEPT.get(d, []))
    pool = [p for p in pool if p["id"] != sender_id]
    if not pool:
        pool = [e for e in EMPLOYEES if e["id"] != sender_id]
    n = rng.randint(1, min(3, len(pool)))
    return rng.sample(pool, n)


def _format(template_str: str, rng: random.Random) -> str:
    return template_str.format(
        he=rng.choice([16, 17, 18, 19, 20]),
        cong=rng.randint(15, 220),
        mw=rng.choice([25, 50, 75, 100, 150, 200]),
        region=rng.choice(["NP15", "SP15", "ZP26", "Path-15", "COB"]),
        pct=rng.randint(3, 42),
        n=rng.choice([1, 2, 3, "IV"]),
        amt=rng.randint(12, 380),
        q=rng.choice([1, 2, 3, 4]),
        year=rng.choice([2000, 2001]),
        ext=rng.randint(5000, 9999),
        cohort=chr(ord("A") + rng.randint(0, 7)),
        group=rng.choice(["West Power", "Gas Trading", "Legal", "Research", "Broadband"]),
        a=rng.randint(8, 15), b=rng.randint(20, 35), c=rng.randint(30, 45),
        cp1=rng.choice(["Duke Energy", "Dynegy", "Williams", "Reliant", "Mirant"]),
        cp2=rng.choice(["El Paso", "Sempra", "Aquila", "TXU", "Calpine"]),
        desk=rng.choice(["West Power", "Gas East", "Broadband", "Weather"]),
        var=rng.randint(3, 55),
        season=rng.choice(["winter", "summer", "shoulder"]),
        hdd=rng.randint(300, 900),
        topic_ext=rng.choice(["the Sacramento hearing", "the FERC roundtable",
                               "the Wall Street Journal briefing",
                               "the analyst day", "the earnings call"]),
        tb=rng.randint(2, 45),
        cities=rng.randint(1, 24),
        cost=rng.randint(45, 240),
        month=rng.choice(["January", "March", "June", "September"]),
        n_txn=rng.randint(1200, 9800),
        products=rng.randint(600, 1500),
    )


def _build_email(idx: int, tmpl: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    sender = _pick_sender(tmpl["dept_from"], rng)
    recipients = _pick_recipients(tmpl["dept_to"], sender["id"], rng)
    subject = _format(tmpl["subject"], rng)
    body    = _format(tmpl["body"], rng)
    d = _START + timedelta(days=rng.randint(0, _DAYS))
    return {
        "id": f"m_{idx:04d}",
        "sender": sender["id"],
        "recipients": [r["id"] for r in recipients],
        "date": d.isoformat(),
        "subject": subject,
        "body": body,
        "topic": tmpl["topic"],
    }


def _generate_emails(n: int = 260, seed: int = 20260201) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    return [_build_email(i, rng.choice(_TEMPLATES), rng) for i in range(1, n + 1)]


EMAILS: List[Dict[str, Any]] = _generate_emails()


# --------------------------------------------------------------------------
# Public views used by retrieval and graph rendering
# --------------------------------------------------------------------------

DEMO_EMPLOYEES = EMPLOYEES       # kept name for backwards compatibility
DEMO_EMAILS    = EMAILS


def employee_by_email(addr: str) -> Dict[str, Any] | None:
    if not addr:
        return None
    for e in EMPLOYEES:
        if e["email"].lower() == addr.lower():
            return e
    return None


def build_demo_graph(max_emails: int = 120) -> Dict[str, Any]:
    """Return a rendering-friendly slice of the full graph.

    A capped size keeps the force-graph responsive; the analytical retrieval
    still runs against the full corpus.
    """
    subset = EMAILS[:max_emails]
    nodes = [
        {"id": e["id"], "label": e["name"], "type": "Employee",
         "department": e["department"], "clearance": e["clearance"]}
        for e in EMPLOYEES
    ]
    for m in subset:
        nodes.append({"id": m["id"], "label": m["subject"][:40],
                      "type": "Email", "date": m["date"]})
    links: List[Dict[str, str]] = []
    for m in subset:
        links.append({"source": m["sender"], "target": m["id"], "rel": "SND_EMAIL"})
        for r in m["recipients"]:
            links.append({"source": m["id"], "target": r, "rel": "RCV_EMAIL"})
    return {"nodes": nodes, "links": links}


def corpus_stats() -> Dict[str, Any]:
    return {
        "employees": len(EMPLOYEES),
        "departments": len(_BY_DEPT),
        "emails": len(EMAILS),
        "relationships": sum(1 + len(m["recipients"]) for m in EMAILS),
    }
