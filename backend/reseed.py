"""
AgentOps — Reseed script
Drops all data and re-runs seed.py with the updated agent definition.
Use this locally during development when you update seed.py.
DO NOT run this against the production database.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

DB_PATH = os.environ.get("AGENTOPS_DB", "agentops.db")

if "production" in DB_PATH.lower() or os.environ.get("RAILWAY_ENVIRONMENT"):
    print("✗ Refusing to reseed — production environment detected.")
    sys.exit(1)

import sqlite3
from database import init_db, migrate_db

# Initialise schema first so tables exist
init_db()
migrate_db()

print(f"Dropping all data from: {DB_PATH}")
conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=OFF")
for table in ["audit_log","approval_requests","cost_records","eval_results",
              "lifecycle_transitions","agent_versions","agents"]:
    conn.execute(f"DELETE FROM {table}")
conn.commit()
conn.close()
print("  OK All tables cleared")

from seed import seed
seed()
