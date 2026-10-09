"""Enron maildir → CSV → Neo4j ETL.

Usage:
  python enron_etl.py parse   /path/to/maildir   ./out
  python enron_etl.py load    ./out   bolt://localhost:7687  neo4j  password

Phase 1 (parse) walks the standard Enron maildir tree (one folder per
employee, sub-folders such as inbox/sent), extracts a normalised set of
CSV files:
    employees.csv   id,name,email,department
    emails.csv      id,sender,date,subject,body
    recipients.csv  email_id,recipient_id,type    # to/cc/bcc

Phase 2 (load) uses Neo4j's built-in LOAD CSV to bulk-import the graph:
    (:Employee {id,name,email,department})
    (:Email    {id,date,subject,body})
    (:Employee)-[:SND_EMAIL]->(:Email)
    (:Email)-[:RCV_EMAIL]->(:Employee)

Notes
-----
* The public Enron corpus is ~1.7 GB uncompressed; run parse phase on a
  workstation, then copy the tiny CSVs into the Neo4j import directory.
* Column headers are stable so the same load phase works if you swap in
  a different email dataset.
"""
from __future__ import annotations

import csv
import email
import hashlib
import os
import re
import sys
from pathlib import Path


ADDR_RE = re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+")


def _id_for(addr: str) -> str:
    return "e_" + hashlib.md5(addr.lower().encode()).hexdigest()[:10]


def _dept_from_folder(root: Path, employee_folder: Path) -> str:
    # e.g. maildir/skilling-j -> Executive if in a known map, else Unknown
    known = {
        "skilling-j": "Executive", "lay-k": "Executive",
        "kaminski-v": "Research", "kean-s": "Public Affairs",
        "belden-t": "West Power", "lavorato-j": "Trading",
        "shackleton-s": "Legal", "sanders-r": "Legal",
        "fastow-a": "Finance", "kitchen-l": "Trading",
        "mann-k": "Legal", "taylor-m": "Legal",
    }
    return known.get(employee_folder.name, "Unknown")


def parse_maildir(maildir: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    employees: dict[str, dict] = {}
    emails_rows: list[list[str]] = []
    recip_rows: list[list[str]] = []
    seen_email_ids: set[str] = set()

    for emp_folder in sorted(p for p in maildir.iterdir() if p.is_dir()):
        for path in emp_folder.rglob("*"):
            if not path.is_file():
                continue
            try:
                with path.open("r", errors="ignore") as f:
                    msg = email.message_from_file(f)
            except Exception:
                continue
            frm = (msg.get("From") or "").strip()
            frm_addrs = ADDR_RE.findall(frm)
            if not frm_addrs:
                continue
            sender = frm_addrs[0].lower()
            sender_id = _id_for(sender)
            if sender_id not in employees:
                employees[sender_id] = {
                    "id": sender_id, "email": sender,
                    "name": sender.split("@")[0].replace(".", " ").title(),
                    "department": _dept_from_folder(maildir, emp_folder),
                }
            subject = (msg.get("Subject") or "").strip().replace("\n", " ")
            date = (msg.get("Date") or "").strip()
            body = msg.get_payload() if not msg.is_multipart() else "\n".join(
                (p.get_payload(decode=True) or b"").decode("utf-8", "ignore")
                for p in msg.walk() if p.get_content_type() == "text/plain"
            )
            body = (body or "")[:4000].replace("\n", " ").strip()
            eid = "m_" + hashlib.md5(f"{sender}|{date}|{subject}".encode()).hexdigest()[:12]
            if eid in seen_email_ids:
                continue
            seen_email_ids.add(eid)
            emails_rows.append([eid, sender_id, date, subject, body])
            for header in ("To", "Cc", "Bcc"):
                for addr in ADDR_RE.findall(msg.get(header) or ""):
                    a = addr.lower()
                    rid = _id_for(a)
                    if rid not in employees:
                        employees[rid] = {"id": rid, "email": a,
                                          "name": a.split("@")[0].replace(".", " ").title(),
                                          "department": "Unknown"}
                    recip_rows.append([eid, rid, header.lower()])

    with (out / "employees.csv").open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["id", "email", "name", "department"])
        for e in employees.values():
            w.writerow([e["id"], e["email"], e["name"], e["department"]])
    with (out / "emails.csv").open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["id", "sender", "date", "subject", "body"])
        w.writerows(emails_rows)
    with (out / "recipients.csv").open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["email_id", "recipient_id", "type"])
        w.writerows(recip_rows)
    print(f"parsed {len(employees)} employees / {len(emails_rows)} emails")


def load_neo4j(csv_dir: Path, uri: str, user: str, password: str) -> None:
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as s:
        s.run("CREATE CONSTRAINT emp_id  IF NOT EXISTS FOR (e:Employee) REQUIRE e.id IS UNIQUE")
        s.run("CREATE CONSTRAINT mail_id IF NOT EXISTS FOR (m:Email)    REQUIRE m.id IS UNIQUE")
        s.run(f"""
            LOAD CSV WITH HEADERS FROM 'file:///employees.csv' AS row
            MERGE (e:Employee {{id: row.id}})
            SET e.email = row.email, e.name = row.name, e.department = row.department
        """)
        s.run(f"""
            LOAD CSV WITH HEADERS FROM 'file:///emails.csv' AS row
            MERGE (m:Email {{id: row.id}})
            SET m.subject = row.subject, m.date = row.date, m.body = row.body
            WITH row, m
            MATCH (e:Employee {{id: row.sender}})
            MERGE (e)-[:SND_EMAIL]->(m)
        """)
        s.run(f"""
            LOAD CSV WITH HEADERS FROM 'file:///recipients.csv' AS row
            MATCH (m:Email {{id: row.email_id}})
            MATCH (e:Employee {{id: row.recipient_id}})
            MERGE (m)-[:RCV_EMAIL {{type: row.type}}]->(e)
        """)
    driver.close()
    print("neo4j load complete")


def main(argv):
    if len(argv) < 2:
        print(__doc__); sys.exit(1)
    cmd = argv[1]
    if cmd == "parse":
        parse_maildir(Path(argv[2]), Path(argv[3]))
    elif cmd == "load":
        load_neo4j(Path(argv[2]), argv[3], argv[4], argv[5])
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main(sys.argv)
