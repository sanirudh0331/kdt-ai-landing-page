"""
Database layer for Neo SQL tools.
Calls Railway services directly via HTTP - exactly like MCP does.
Includes query caching to avoid repeated calls.
"""

import os
import time
import hashlib
import httpx
from typing import Optional

# Railway service URLs - direct database access endpoints
SERVICE_URLS = {
    "researchers": os.environ.get("RESEARCHERS_SERVICE_URL", "https://kdttalentscout.up.railway.app"),
    "patents": os.environ.get("PATENTS_SERVICE_URL", "https://patentwarrior.up.railway.app"),
    "grants": os.environ.get("GRANTS_SERVICE_URL", "https://grants-tracker-production.up.railway.app"),
    "policies": os.environ.get("POLICIES_SERVICE_URL", "https://policywatch.up.railway.app"),
    "portfolio": os.environ.get("PORTFOLIO_SERVICE_URL", "https://web-production-a9d068.up.railway.app"),
    "market_data": os.environ.get("MARKET_DATA_SERVICE_URL", "https://clinicaltrialsdata.up.railway.app"),
}

# Optional secret for SQL endpoints
NEO_SQL_SECRET = os.environ.get("NEO_SQL_SECRET", "")

# Query cache: {cache_key: {"result": ..., "timestamp": ...}}
_query_cache = {}
CACHE_TTL = 300  # 5 minutes


def _cache_key(db_name: str, query: str) -> str:
    """Generate cache key from db name and query."""
    normalized = f"{db_name}:{query.strip().lower()}"
    return hashlib.md5(normalized.encode()).hexdigest()


def _get_cached(key: str) -> Optional[dict]:
    """Get cached result if not expired."""
    if key in _query_cache:
        entry = _query_cache[key]
        if time.time() - entry["timestamp"] < CACHE_TTL:
            return entry["result"]
        else:
            del _query_cache[key]
    return None


def _set_cached(key: str, result: dict):
    """Cache a query result."""
    # Limit cache size (simple LRU-ish: just clear if too big)
    if len(_query_cache) > 100:
        # Remove oldest half
        sorted_keys = sorted(_query_cache.keys(), key=lambda k: _query_cache[k]["timestamp"])
        for k in sorted_keys[:50]:
            del _query_cache[k]

    _query_cache[key] = {"result": result, "timestamp": time.time()}


def execute_query(db_name: str, query: str, limit: int = 100, use_cache: bool = True) -> dict:
    """
    Execute a SELECT query against the specified database via HTTP.

    This calls the /api/sql endpoint on each Railway service -
    exactly like MCP provides direct database access.

    Args:
        db_name: Which database to query (researchers, patents, grants, policies, portfolio)
        query: SQL SELECT query to execute
        limit: Maximum rows to return (default 100)
        use_cache: Whether to use query caching (default True)

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

    # Check cache first
    if use_cache:
        cache_key = _cache_key(db_name, query)
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

    # Execute query with retry on timeout
    max_retries = 2
    last_error = None

    for attempt in range(max_retries):
        try:
            timeout = 90 if attempt == 0 else 120  # Longer timeout on retry
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    url,
                    json={"query": query, "secret": NEO_SQL_SECRET},
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                result = response.json()

                # Cache successful result
                if use_cache:
                    _set_cached(cache_key, result)

                return result

        except httpx.TimeoutException as e:
            last_error = f"Query timed out (attempt {attempt + 1}/{max_retries})"
            if attempt < max_retries - 1:
                continue  # Retry
            raise ValueError(f"Query timed out after {max_retries} attempts. Try a simpler query with more restrictive WHERE clauses.")

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


def clear_cache():
    """Clear the query cache."""
    global _query_cache
    _query_cache = {}


def get_cache_stats() -> dict:
    """Get cache statistics."""
    return {
        "entries": len(_query_cache),
        "max_entries": 100,
        "ttl_seconds": CACHE_TTL,
    }


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
