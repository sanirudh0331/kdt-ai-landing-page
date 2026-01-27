"""
Database layer for Neo SQL tools.
Provides direct SQL access to KdT databases - replicating MCP functionality.
"""

import sqlite3
import os
from pathlib import Path
from typing import Optional

# Database paths - these will be in the data/ directory when deployed
DATA_DIR = Path(__file__).parent.parent / "data"

DATABASES = {
    "researchers": DATA_DIR / "researchers.db",
    "patents": DATA_DIR / "patents.db",
    "grants": DATA_DIR / "grants.db",
    "policies": DATA_DIR / "policies.db",
    "portfolio": DATA_DIR / "portfolio.db",
}

# Allow override via environment variables for flexibility
DB_PATHS = {
    "researchers": Path(os.environ.get("RESEARCHERS_DB_PATH", DATABASES["researchers"])),
    "patents": Path(os.environ.get("PATENTS_DB_PATH", DATABASES["patents"])),
    "grants": Path(os.environ.get("GRANTS_DB_PATH", DATABASES["grants"])),
    "policies": Path(os.environ.get("POLICIES_DB_PATH", DATABASES["policies"])),
    "portfolio": Path(os.environ.get("PORTFOLIO_DB_PATH", DATABASES["portfolio"])),
}


def get_connection(db_name: str) -> sqlite3.Connection:
    """Get a connection to the specified database."""
    if db_name not in DB_PATHS:
        raise ValueError(f"Unknown database: {db_name}. Valid: {list(DB_PATHS.keys())}")

    db_path = DB_PATHS[db_name]
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Return dicts instead of tuples
    return conn


def execute_query(db_name: str, query: str, limit: int = 100) -> dict:
    """
    Execute a SELECT query against the specified database.

    Args:
        db_name: Which database to query (researchers, patents, grants, policies, portfolio)
        query: SQL SELECT query to execute
        limit: Maximum rows to return (default 100, max 500)

    Returns:
        dict with 'columns', 'rows', 'row_count'
    """
    # Security: Only allow SELECT statements
    query_upper = query.strip().upper()
    if not query_upper.startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed")

    # Block dangerous keywords
    dangerous = ["DELETE", "DROP", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE", "EXEC", "EXECUTE"]
    for keyword in dangerous:
        if keyword in query_upper:
            raise ValueError(f"Query contains forbidden keyword: {keyword}")

    # Enforce limit
    limit = min(limit, 500)

    # Add LIMIT if not present
    if "LIMIT" not in query_upper:
        query = f"{query.rstrip(';')} LIMIT {limit}"

    conn = get_connection(db_name)
    try:
        cursor = conn.execute(query)
        columns = [description[0] for description in cursor.description]
        rows = [dict(row) for row in cursor.fetchall()]

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    finally:
        conn.close()


def list_tables(db_name: str) -> list[dict]:
    """List all tables in the specified database."""
    conn = get_connection(db_name)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [{"name": row["name"]} for row in cursor.fetchall()]
    finally:
        conn.close()


def describe_table(db_name: str, table_name: str) -> list[dict]:
    """Get schema information for a specific table."""
    conn = get_connection(db_name)
    try:
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        return [
            {
                "cid": row["cid"],
                "name": row["name"],
                "type": row["type"],
                "notnull": row["notnull"],
                "default": row["dflt_value"],
                "pk": row["pk"],
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def get_database_stats() -> dict:
    """Get statistics about all available databases."""
    stats = {}
    for db_name, db_path in DB_PATHS.items():
        if db_path.exists():
            try:
                tables = list_tables(db_name)
                table_counts = {}
                conn = get_connection(db_name)
                for table in tables:
                    cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM {table['name']}")
                    table_counts[table["name"]] = cursor.fetchone()["cnt"]
                conn.close()

                stats[db_name] = {
                    "available": True,
                    "path": str(db_path),
                    "size_mb": round(db_path.stat().st_size / (1024 * 1024), 2),
                    "tables": table_counts,
                }
            except Exception as e:
                stats[db_name] = {"available": False, "error": str(e)}
        else:
            stats[db_name] = {"available": False, "error": "File not found"}

    return stats


if __name__ == "__main__":
    # Quick test
    print("Database Stats:")
    print("-" * 50)
    stats = get_database_stats()
    for db, info in stats.items():
        print(f"\n{db}:")
        if info.get("available"):
            print(f"  Size: {info['size_mb']} MB")
            print(f"  Tables: {info['tables']}")
        else:
            print(f"  Error: {info.get('error')}")
