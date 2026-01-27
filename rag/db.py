"""
Database layer for Neo SQL tools.
Calls Railway services directly via HTTP - exactly like MCP does.
"""

import os
import httpx
from typing import Optional

# Railway service URLs - direct database access endpoints
SERVICE_URLS = {
    "researchers": os.environ.get("RESEARCHERS_SERVICE_URL", "https://kdttalentscout.up.railway.app"),
    "patents": os.environ.get("PATENTS_SERVICE_URL", "https://patentwarrior.up.railway.app"),
    "grants": os.environ.get("GRANTS_SERVICE_URL", "https://grants-tracker-production.up.railway.app"),
    "policies": os.environ.get("POLICIES_SERVICE_URL", "https://policywatch.up.railway.app"),
    "portfolio": os.environ.get("PORTFOLIO_SERVICE_URL", "https://web-production-a9d068.up.railway.app"),
}

# Optional secret for SQL endpoints
NEO_SQL_SECRET = os.environ.get("NEO_SQL_SECRET", "")


def execute_query(db_name: str, query: str, limit: int = 100) -> dict:
    """
    Execute a SELECT query against the specified database via HTTP.

    This calls the /api/sql endpoint on each Railway service -
    exactly like MCP provides direct database access.

    Args:
        db_name: Which database to query (researchers, patents, grants, policies, portfolio)
        query: SQL SELECT query to execute
        limit: Maximum rows to return (default 100)

    Returns:
        dict with 'columns', 'rows', 'row_count'
    """
    if db_name not in SERVICE_URLS:
        raise ValueError(f"Unknown database: {db_name}. Valid: {list(SERVICE_URLS.keys())}")

    base_url = SERVICE_URLS[db_name]
    url = f"{base_url}/api/sql"

    # Add LIMIT if not present (safety)
    query_upper = query.strip().upper()
    if "LIMIT" not in query_upper:
        limit = min(limit, 500)
        query = f"{query.rstrip(';')} LIMIT {limit}"

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                url,
                json={"query": query, "secret": NEO_SQL_SECRET},
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_detail = e.response.json().get("detail", str(e)) if e.response.content else str(e)
        raise ValueError(f"Query error: {error_detail}")
    except Exception as e:
        raise ValueError(f"Failed to query {db_name}: {str(e)}")


def list_tables(db_name: str) -> list[dict]:
    """List all tables in the specified database."""
    if db_name not in SERVICE_URLS:
        raise ValueError(f"Unknown database: {db_name}. Valid: {list(SERVICE_URLS.keys())}")

    base_url = SERVICE_URLS[db_name]
    url = f"{base_url}/api/sql/tables"

    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
            return [{"name": t} for t in data.get("tables", [])]
    except Exception as e:
        raise ValueError(f"Failed to list tables for {db_name}: {str(e)}")


def describe_table(db_name: str, table_name: str) -> list[dict]:
    """Get schema information for a specific table."""
    if db_name not in SERVICE_URLS:
        raise ValueError(f"Unknown database: {db_name}. Valid: {list(SERVICE_URLS.keys())}")

    base_url = SERVICE_URLS[db_name]
    url = f"{base_url}/api/sql/schema/{table_name}"

    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("columns", [])
    except Exception as e:
        raise ValueError(f"Failed to describe {table_name} in {db_name}: {str(e)}")


def get_database_stats() -> dict:
    """Get statistics about all available databases."""
    stats = {}
    for db_name, base_url in SERVICE_URLS.items():
        try:
            tables = list_tables(db_name)
            table_counts = {}
            for table in tables:
                try:
                    result = execute_query(db_name, f"SELECT COUNT(*) as cnt FROM {table['name']}")
                    table_counts[table["name"]] = result["rows"][0]["cnt"] if result["rows"] else 0
                except:
                    table_counts[table["name"]] = "error"

            stats[db_name] = {
                "available": True,
                "url": base_url,
                "tables": table_counts,
            }
        except Exception as e:
            stats[db_name] = {"available": False, "error": str(e)}

    return stats


if __name__ == "__main__":
    # Quick test
    print("Database Stats (via Railway services):")
    print("-" * 50)
    stats = get_database_stats()
    for db, info in stats.items():
        print(f"\n{db}:")
        if info.get("available"):
            print(f"  URL: {info['url']}")
            print(f"  Tables: {info['tables']}")
        else:
            print(f"  Error: {info.get('error')}")
