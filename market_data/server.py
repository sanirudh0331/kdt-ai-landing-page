"""
KdT Market Data Service
Serves FDA calendar and clinical trials data via SQL API.
"""

import os
import json
import sqlite3
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Paths
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
FDA_DB_PATH = DATA_DIR / "fda_calendar.db"
TRIALS_DB_PATH = DATA_DIR / "clinical_trials.db"

# Optional secret for SQL endpoints
NEO_SQL_SECRET = os.environ.get("NEO_SQL_SECRET", "")

app = FastAPI(title="KdT Market Data", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SQLRequest(BaseModel):
    query: str
    secret: Optional[str] = ""


@contextmanager
def get_db_connection(db_path: Path):
    """Context manager for database connections."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_all_tables() -> list[str]:
    """Get all tables from both databases."""
    tables = []

    if FDA_DB_PATH.exists():
        with get_db_connection(FDA_DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables.extend([row["name"] for row in cursor])

    if TRIALS_DB_PATH.exists():
        with get_db_connection(TRIALS_DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables.extend([row["name"] for row in cursor])

    return tables


def find_table_db(table_name: str) -> Optional[Path]:
    """Find which database contains a table."""
    for db_path in [FDA_DB_PATH, TRIALS_DB_PATH]:
        if db_path.exists():
            with get_db_connection(db_path) as conn:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,)
                )
                if cursor.fetchone():
                    return db_path
    return None


@app.get("/")
def health():
    """Health check endpoint."""
    fda_exists = FDA_DB_PATH.exists()
    trials_exists = TRIALS_DB_PATH.exists()

    return {
        "service": "KdT Market Data",
        "status": "healthy",
        "databases": {
            "fda_calendar": {
                "path": str(FDA_DB_PATH),
                "exists": fda_exists,
            },
            "clinical_trials": {
                "path": str(TRIALS_DB_PATH),
                "exists": trials_exists,
            },
        },
    }


@app.get("/api/sql/tables")
def list_tables():
    """List all available tables."""
    return {"tables": get_all_tables()}


@app.get("/api/sql/schema/{table_name}")
def get_schema(table_name: str):
    """Get schema for a specific table."""
    db_path = find_table_db(table_name)
    if not db_path:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    with get_db_connection(db_path) as conn:
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        columns = [
            {
                "name": row["name"],
                "type": row["type"],
                "notnull": bool(row["notnull"]),
                "pk": bool(row["pk"]),
            }
            for row in cursor
        ]

    return {"table": table_name, "columns": columns}


@app.post("/api/sql")
def execute_sql(request: SQLRequest):
    """Execute a SELECT query."""
    # Validate secret if configured
    if NEO_SQL_SECRET and request.secret != NEO_SQL_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    query = request.query.strip()

    # Only allow SELECT queries
    if not query.upper().startswith("SELECT"):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")

    # Determine which database to query based on table name
    query_upper = query.upper()

    if "FDA_EVENTS" in query_upper:
        db_path = FDA_DB_PATH
    elif "CLINICAL_TRIALS" in query_upper:
        db_path = TRIALS_DB_PATH
    else:
        # Try to find the table
        # Extract table name from query (basic parsing)
        for table in get_all_tables():
            if table.upper() in query_upper:
                db_path = find_table_db(table)
                break
        else:
            raise HTTPException(
                status_code=400,
                detail="Could not determine which database to query. Available tables: " + ", ".join(get_all_tables())
            )

    if not db_path or not db_path.exists():
        raise HTTPException(status_code=404, detail=f"Database not found: {db_path}")

    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.execute(query)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = [dict(row) for row in cursor.fetchall()]

            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            }
    except sqlite3.Error as e:
        raise HTTPException(status_code=400, detail=f"SQL error: {str(e)}")


@app.get("/api/stats")
def get_stats():
    """Get statistics about the data."""
    stats = {}

    if FDA_DB_PATH.exists():
        with get_db_connection(FDA_DB_PATH) as conn:
            cursor = conn.execute("SELECT COUNT(*) as count FROM fda_events")
            row = cursor.fetchone()
            stats["fda_events"] = row["count"] if row else 0

            # Upcoming events
            cursor = conn.execute("""
                SELECT COUNT(*) as count FROM fda_events
                WHERE event_date >= date('now')
            """)
            row = cursor.fetchone()
            stats["fda_upcoming"] = row["count"] if row else 0

    if TRIALS_DB_PATH.exists():
        with get_db_connection(TRIALS_DB_PATH) as conn:
            cursor = conn.execute("SELECT COUNT(*) as count FROM clinical_trials")
            row = cursor.fetchone()
            stats["clinical_trials"] = row["count"] if row else 0

            # By status
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count FROM clinical_trials
                GROUP BY status ORDER BY count DESC LIMIT 5
            """)
            stats["trials_by_status"] = {row["status"]: row["count"] for row in cursor}

    return stats


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
