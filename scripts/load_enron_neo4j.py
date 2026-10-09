"""Load the cleaned Enron Neo4j dataset into a running Neo4j instance.

Usage:
  python load_enron_neo4j.py [bolt://localhost:7687] [neo4j] [password] [path/to/zip]
"""
from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

POSSIBLE_ZIP_PATHS = [
    os.environ.get("ENRON_ZIP_PATH"),
    r"C:\Users\ldeep\Downloads\AegisGraph_Enron_Neo4j_Dataset_claude.zip",
    r"C:\Users\ldeep\Downloads\aegisgraph_enron_neo4j_dataset_claude.zip",
]


def find_zip() -> str:
    for p in POSSIBLE_ZIP_PATHS:
        if p and os.path.exists(p):
            return p
    raise FileNotFoundError("Could not find AegisGraph_Enron_Neo4j_Dataset_claude.zip in Downloads or current folder.")


def main():
    uri = sys.argv[1] if len(sys.argv) > 1 else "bolt://localhost:7687"
    user = sys.argv[2] if len(sys.argv) > 2 else "neo4j"
    pwd = sys.argv[3] if len(sys.argv) > 3 else "password"
    zip_path = sys.argv[4] if len(sys.argv) > 4 else find_zip()

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("neo4j driver not installed. Run: pip install neo4j")
        sys.exit(1)

    print(f"Connecting to Neo4j at {uri} as {user}...")
    driver = GraphDatabase.driver(uri, auth=(user, pwd))

    try:
        with driver.session() as s:
            s.run("RETURN 1").consume()
        print("Connected successfully!")
    except Exception as e:
        print(f"Failed to connect to Neo4j: {e}")
        sys.exit(1)

    with zipfile.ZipFile(zip_path) as z:
        cypher_script = z.read("neo4j_import/import_load_csv.cypher").decode("utf-8")

    print("\nDataset ready.")
    print("To load into Neo4j Desktop:")
    print("1. In Neo4j Desktop, select your DBMS -> '...' -> 'Open folder' -> 'Import'")
    print(f"2. Extract the CSV files from '{zip_path}' (inside neo4j_import/) into that 'import' folder.")
    print("3. In Neo4j Browser, execute the Cypher statements from 'import_load_csv.cypher'.")
    print("\nOr run constraints setup now:")
    with driver.session() as s:
        s.run("CREATE CONSTRAINT person_email IF NOT EXISTS FOR (p:Person) REQUIRE p.email IS UNIQUE")
        s.run("CREATE CONSTRAINT email_id IF NOT EXISTS FOR (e:Email) REQUIRE e.email_id IS UNIQUE")
        s.run("CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE")
    print("Constraints created successfully in Neo4j.")
    driver.close()


if __name__ == "__main__":
    main()
