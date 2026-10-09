# Enron → Neo4j ETL

`enron_etl.py` is a two-phase pipeline that ingests the classic
Enron maildir dataset into a Neo4j graph shaped for AegisGraph.

## 1. Get the dataset

```
curl -O https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz
tar -xzf enron_mail_20150507.tar.gz
```

The archive expands to `maildir/<employee>/{inbox,sent_items,...}/`.

## 2. Parse to CSVs

```
python enron_etl.py parse ./maildir ./out
```

This writes three normalised files:

| file            | columns                                     |
| --------------- | ------------------------------------------- |
| employees.csv   | id, email, name, department                 |
| emails.csv      | id, sender, date, subject, body             |
| recipients.csv  | email_id, recipient_id, type (to/cc/bcc)    |

Departments are inferred from the folder-name map at the top of the script.
Adjust that dict if you want richer HR data.

## 3. Load into Neo4j

Copy the three CSVs into the `import/` folder of your Neo4j instance
(Neo4j Desktop: **Manage → Open Folder → Import**), then:

```
python enron_etl.py load ./out bolt://localhost:7687 neo4j <password>
```

The script uses `LOAD CSV WITH HEADERS` under the hood; it is idempotent
thanks to the `MERGE` clauses and the two uniqueness constraints it
creates on first run.

## 4. Point AegisGraph at your database

Configure `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and (if needed)
`NEO4J_DATABASE` in `backend/.env`, or use the app's **Connect Neo4j**
control for a per-user connection. The query pipeline requires a populated
Neo4j graph; it does not fall back to bundled demo records.

The `enron_etl.py` loader above creates the older
`Employee`/`SND_EMAIL`/`RCV_EMAIL` schema. AegisGraph can query that schema
through its literal compatibility path, but semantic vector retrieval expects
the current `Person`/`SENT`/`SENT_TO` schema and `Email.email_id` identifiers.
Build the semantic index after loading a compatible graph:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe scripts\build_semantic_index.py
```

## What the app does when Neo4j is offline

Queries fail with an explicit service-unavailable response when Neo4j cannot
be reached or has no usable `Person`/`Email` graph. Demo data remains in the
codebase for profile defaults, redaction support, and fixtures; it is not
used as a retrieval substitute.
