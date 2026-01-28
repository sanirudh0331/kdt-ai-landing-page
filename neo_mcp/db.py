"""
Database layer for Neo SQL tools.
Calls Railway services directly via HTTP - exactly like MCP does.
Includes query caching to avoid repeated calls.
"""

import os
import json
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


# SEC Sentinel service URL
SEC_SENTINEL_URL = os.environ.get("SEC_SENTINEL_URL", "https://secsentinel.up.railway.app")


# =============================================================================
# SEC SENTINEL SEMANTIC FUNCTIONS
# =============================================================================

def get_sec_filings(
    ticker: str = None,
    form_type: str = None,
    days: int = 30,
    runway_status: str = None
) -> dict:
    """Get SEC filings with optional filters and runway context."""
    params = {"days": days}
    if ticker:
        params["ticker"] = ticker
    if form_type:
        params["form_type"] = form_type
    if runway_status:
        params["runway_status"] = runway_status

    cache_key = _cache_key("sec", f"filings:{json.dumps(params, sort_keys=True)}")
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{SEC_SENTINEL_URL}/api/semantic/filings", params=params)
            response.raise_for_status()
            result = response.json()
            _set_cached(cache_key, result)
            return result
    except Exception as e:
        return {"error": str(e), "filings": [], "count": 0}


def get_companies_by_runway(
    max_months: float = None,
    min_months: float = 0,
    limit: int = 50
) -> dict:
    """Get companies sorted by runway status."""
    params = {"min_months": min_months, "limit": limit}
    if max_months:
        params["max_months"] = max_months

    cache_key = _cache_key("sec", f"runway:{json.dumps(params, sort_keys=True)}")
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{SEC_SENTINEL_URL}/api/semantic/runway", params=params)
            response.raise_for_status()
            result = response.json()
            _set_cached(cache_key, result)
            return result
    except Exception as e:
        return {"error": str(e), "companies": [], "count": 0}


def get_insider_transactions(
    ticker: str = None,
    insider_role: str = None,
    transaction_type: str = None,
    days: int = 90,
    min_value: float = 0
) -> dict:
    """Get insider transactions with runway context."""
    params = {"days": days}
    if ticker:
        params["ticker"] = ticker
    if insider_role:
        params["insider_role"] = insider_role
    if transaction_type:
        params["transaction_type"] = transaction_type
    if min_value:
        params["min_value"] = min_value

    cache_key = _cache_key("sec", f"insider:{json.dumps(params, sort_keys=True)}")
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{SEC_SENTINEL_URL}/api/semantic/insider", params=params)
            response.raise_for_status()
            result = response.json()
            _set_cached(cache_key, result)
            return result
    except Exception as e:
        return {"error": str(e), "transactions": [], "count": 0}


def get_runway_alerts() -> dict:
    """Get runway distress alerts."""
    cache_key = _cache_key("sec", "runway_alerts")
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{SEC_SENTINEL_URL}/api/semantic/alerts")
            response.raise_for_status()
            result = response.json()
            _set_cached(cache_key, result)
            return result
    except Exception as e:
        return {"error": str(e), "critical_runway": [], "recent_s3_filings": [], "insider_sells_at_risk": []}


# =============================================================================
# SEMANTIC FUNCTIONS - Structured, validated queries with business context
# =============================================================================

def get_researchers(
    min_h_index: int = None,
    topic: str = None,
    affiliation: str = None,
    limit: int = 20
) -> dict:
    """Find researchers with optional filters."""
    conditions = []
    if min_h_index:
        conditions.append(f"h_index >= {int(min_h_index)}")
    if topic:
        conditions.append(f"topics LIKE '%{topic}%'")
    if affiliation:
        conditions.append(f"affiliations LIKE '%{affiliation}%'")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    query = f"""
        SELECT id, name, h_index, slope, affiliations, topics, primary_category,
               works_count, cited_by_count
        FROM researchers
        WHERE {where_clause}
        ORDER BY h_index DESC
        LIMIT {int(limit)}
    """
    return execute_query("researchers", query)


def get_researcher_profile(name: str) -> dict:
    """Get detailed profile for a specific researcher."""
    # Get researcher basic info
    query = f"""
        SELECT r.*,
               (SELECT GROUP_CONCAT(year || ':' || h_index, ', ')
                FROM h_index_history
                WHERE researcher_id = r.id
                ORDER BY year DESC
                LIMIT 10) as recent_history
        FROM researchers r
        WHERE r.name LIKE '%{name}%'
        LIMIT 5
    """
    result = execute_query("researchers", query)

    if result.get("rows"):
        # Add trajectory analysis
        for row in result["rows"]:
            slope = row.get("slope", 0) or 0
            h_index = row.get("h_index", 0) or 0
            if slope > 3 and h_index < 60:
                row["trajectory"] = "Rising Star - fast-growing impact"
            elif slope > 1.5:
                row["trajectory"] = "Growing - strong upward trend"
            elif slope > 0:
                row["trajectory"] = "Stable - steady output"
            else:
                row["trajectory"] = "Established - mature career"

    return result


def get_rising_stars(
    min_slope: float = 2.0,
    min_h_index: int = 15,
    max_h_index: int = 80,
    topic: str = None,
    limit: int = 20
) -> dict:
    """Find researchers with fast-growing h-index."""
    topic_filter = f"AND topics LIKE '%{topic}%'" if topic else ""

    query = f"""
        SELECT id, name, h_index, slope, affiliations, topics, primary_category
        FROM researchers
        WHERE slope >= {float(min_slope)}
          AND h_index >= {int(min_h_index)}
          AND h_index <= {int(max_h_index)}
          {topic_filter}
        ORDER BY slope DESC
        LIMIT {int(limit)}
    """
    result = execute_query("researchers", query)

    # Add context about what rising stars means
    result["_context"] = {
        "description": "Rising stars are researchers with h-index growth rate above peers",
        "criteria": f"slope >= {min_slope}, h-index {min_h_index}-{max_h_index}",
        "insight": "High slope indicates rapid career growth - good candidates for collaboration or hiring"
    }
    return result


def get_researchers_by_topic(topic: str, limit: int = 20) -> dict:
    """Find top researchers in a specific topic area."""
    query = f"""
        SELECT id, name, h_index, slope, affiliations, topics, primary_category
        FROM researchers
        WHERE topics LIKE '%{topic}%'
        ORDER BY h_index DESC
        LIMIT {int(limit)}
    """
    result = execute_query("researchers", query)
    result["_context"] = {
        "topic": topic,
        "insight": f"Top researchers by h-index in {topic}"
    }
    return result


def get_patents(
    assignee: str = None,
    inventor: str = None,
    cpc_code: str = None,
    days: int = None,
    keyword: str = None,
    limit: int = 20
) -> dict:
    """Search patents with filters."""
    conditions = []
    joins = ""

    if assignee:
        conditions.append(f"p.primary_assignee LIKE '%{assignee}%'")
    if inventor:
        joins = "JOIN inventors i ON p.id = i.patent_id"
        conditions.append(f"i.name LIKE '%{inventor}%'")
    if cpc_code:
        conditions.append(f"p.cpc_codes LIKE '%{cpc_code}%'")
    if days:
        conditions.append(f"p.grant_date >= date('now', '-{int(days)} days')")
    if keyword:
        conditions.append(f"(p.title LIKE '%{keyword}%' OR p.abstract LIKE '%{keyword}%')")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    query = f"""
        SELECT DISTINCT p.id, p.patent_number, p.title, p.grant_date, p.filing_date,
               p.primary_assignee, p.cpc_codes, p.claims_count
        FROM patents p
        {joins}
        WHERE {where_clause}
        ORDER BY p.grant_date DESC
        LIMIT {int(limit)}
    """
    return execute_query("patents", query)


def get_patent_portfolio(assignee: str) -> dict:
    """Get patent portfolio summary for a company."""
    # Get patent count and list
    patents_query = f"""
        SELECT id, patent_number, title, grant_date, cpc_codes, claims_count
        FROM patents
        WHERE primary_assignee LIKE '%{assignee}%'
        ORDER BY grant_date DESC
        LIMIT 50
    """
    patents_result = execute_query("patents", patents_query)

    # Get summary stats
    stats_query = f"""
        SELECT
            COUNT(*) as total_patents,
            MIN(grant_date) as earliest_patent,
            MAX(grant_date) as latest_patent,
            AVG(claims_count) as avg_claims
        FROM patents
        WHERE primary_assignee LIKE '%{assignee}%'
    """
    stats_result = execute_query("patents", stats_query)

    return {
        "assignee": assignee,
        "summary": stats_result.get("rows", [{}])[0] if stats_result.get("rows") else {},
        "patents": patents_result.get("rows", []),
        "row_count": patents_result.get("row_count", 0),
        "_context": {
            "insight": f"Patent portfolio analysis for {assignee}"
        }
    }


def get_inventors_by_company(assignee: str, limit: int = 20) -> dict:
    """Get top inventors at a company."""
    query = f"""
        SELECT i.name, COUNT(*) as patent_count,
               GROUP_CONCAT(DISTINCT p.cpc_codes) as technology_areas
        FROM inventors i
        JOIN patents p ON i.patent_id = p.id
        WHERE p.primary_assignee LIKE '%{assignee}%'
        GROUP BY i.name
        ORDER BY patent_count DESC
        LIMIT {int(limit)}
    """
    result = execute_query("patents", query)
    result["_context"] = {
        "assignee": assignee,
        "insight": f"Prolific inventors at {assignee} - potential key personnel"
    }
    return result


def search_patents_by_topic(keywords: str, limit: int = 20) -> dict:
    """Search patents by technology topic."""
    query = f"""
        SELECT id, patent_number, title, grant_date, primary_assignee, cpc_codes, abstract
        FROM patents
        WHERE title LIKE '%{keywords}%' OR abstract LIKE '%{keywords}%'
        ORDER BY grant_date DESC
        LIMIT {int(limit)}
    """
    result = execute_query("patents", query)
    result["_context"] = {
        "keywords": keywords,
        "insight": f"Patent landscape for '{keywords}'"
    }
    return result


def get_grants(
    organization: str = None,
    pi_name: str = None,
    mechanism: str = None,
    min_amount: int = None,
    institute: str = None,
    keyword: str = None,
    limit: int = 20
) -> dict:
    """Search grants with filters."""
    conditions = []
    joins = ""

    if organization:
        conditions.append(f"g.organization LIKE '%{organization}%'")
    if pi_name:
        joins = "JOIN principal_investigators pi ON g.id = pi.grant_id"
        conditions.append(f"pi.name LIKE '%{pi_name}%'")
    if mechanism:
        conditions.append(f"g.mechanism LIKE '%{mechanism}%'")
    if min_amount:
        conditions.append(f"g.total_cost >= {int(min_amount)}")
    if institute:
        conditions.append(f"g.institute LIKE '%{institute}%'")
    if keyword:
        conditions.append(f"(g.title LIKE '%{keyword}%' OR g.abstract LIKE '%{keyword}%')")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    query = f"""
        SELECT DISTINCT g.id, g.title, g.organization, g.mechanism, g.institute,
               g.total_cost, g.start_date, g.end_date, g.fiscal_year
        FROM grants g
        {joins}
        WHERE {where_clause}
        ORDER BY g.total_cost DESC
        LIMIT {int(limit)}
    """
    return execute_query("grants", query)


def get_funding_summary(organization: str) -> dict:
    """Get funding summary for an organization."""
    # Total funding
    total_query = f"""
        SELECT
            COUNT(*) as grant_count,
            SUM(total_cost) as total_funding,
            AVG(total_cost) as avg_grant_size,
            MIN(start_date) as earliest_grant,
            MAX(start_date) as latest_grant
        FROM grants
        WHERE organization LIKE '%{organization}%'
    """
    total_result = execute_query("grants", total_query)

    # By mechanism
    mechanism_query = f"""
        SELECT mechanism, COUNT(*) as count, SUM(total_cost) as funding
        FROM grants
        WHERE organization LIKE '%{organization}%'
        GROUP BY mechanism
        ORDER BY funding DESC
        LIMIT 10
    """
    mechanism_result = execute_query("grants", mechanism_query)

    # Top grants
    top_query = f"""
        SELECT id, title, mechanism, total_cost, start_date
        FROM grants
        WHERE organization LIKE '%{organization}%'
        ORDER BY total_cost DESC
        LIMIT 10
    """
    top_result = execute_query("grants", top_query)

    return {
        "organization": organization,
        "summary": total_result.get("rows", [{}])[0] if total_result.get("rows") else {},
        "by_mechanism": mechanism_result.get("rows", []),
        "top_grants": top_result.get("rows", []),
        "_context": {
            "insight": f"Research funding analysis for {organization}"
        }
    }


def get_pis_by_organization(organization: str, limit: int = 20) -> dict:
    """Get principal investigators at an organization."""
    query = f"""
        SELECT pi.name, COUNT(*) as grant_count, SUM(g.total_cost) as total_funding
        FROM principal_investigators pi
        JOIN grants g ON pi.grant_id = g.id
        WHERE g.organization LIKE '%{organization}%'
        GROUP BY pi.name
        ORDER BY total_funding DESC
        LIMIT {int(limit)}
    """
    result = execute_query("grants", query)
    result["_context"] = {
        "organization": organization,
        "insight": f"Top-funded researchers at {organization}"
    }
    return result


def get_grants_by_topic(keywords: str, limit: int = 20) -> dict:
    """Search grants by research topic."""
    query = f"""
        SELECT id, title, organization, mechanism, institute, total_cost, start_date
        FROM grants
        WHERE title LIKE '%{keywords}%' OR abstract LIKE '%{keywords}%'
        ORDER BY total_cost DESC
        LIMIT {int(limit)}
    """
    result = execute_query("grants", query)
    result["_context"] = {
        "keywords": keywords,
        "insight": f"Research funding landscape for '{keywords}'"
    }
    return result


def search_entity(name: str) -> dict:
    """Search for an entity across all databases."""
    results = {
        "query": name,
        "found_in": [],
        "details": {}
    }

    # Check entity_links table first
    links_query = f"""
        SELECT * FROM entity_links
        WHERE canonical_name LIKE '%{name}%'
           OR aliases LIKE '%{name}%'
           OR patent_assignee_name LIKE '%{name}%'
           OR grant_org_name LIKE '%{name}%'
        LIMIT 5
    """
    try:
        links = execute_query("grants", links_query)
        if links.get("rows"):
            results["entity_links"] = links["rows"]
    except:
        pass

    # Search patents
    try:
        patents = execute_query("patents", f"""
            SELECT COUNT(*) as count FROM patents
            WHERE primary_assignee LIKE '%{name}%'
        """)
        if patents.get("rows") and patents["rows"][0].get("count", 0) > 0:
            results["found_in"].append("patents")
            results["details"]["patents"] = {
                "count": patents["rows"][0]["count"],
                "type": "assignee"
            }
    except:
        pass

    # Search grants
    try:
        grants = execute_query("grants", f"""
            SELECT COUNT(*) as count, SUM(total_cost) as total_funding
            FROM grants WHERE organization LIKE '%{name}%'
        """)
        if grants.get("rows") and grants["rows"][0].get("count", 0) > 0:
            results["found_in"].append("grants")
            results["details"]["grants"] = {
                "count": grants["rows"][0]["count"],
                "total_funding": grants["rows"][0].get("total_funding", 0)
            }
    except:
        pass

    # Search researchers (by affiliation)
    try:
        researchers = execute_query("researchers", f"""
            SELECT COUNT(*) as count FROM researchers
            WHERE affiliations LIKE '%{name}%'
        """)
        if researchers.get("rows") and researchers["rows"][0].get("count", 0) > 0:
            results["found_in"].append("researchers")
            results["details"]["researchers"] = {
                "affiliated_count": researchers["rows"][0]["count"]
            }
    except:
        pass

    results["_context"] = {
        "insight": f"Cross-database search for '{name}'"
    }
    return results


def get_company_profile(name: str) -> dict:
    """Get unified company profile from all databases."""
    profile = {
        "name": name,
        "patents": None,
        "grants": None,
        "researchers": None,
        "_context": {}
    }

    # Get patent data
    try:
        profile["patents"] = get_patent_portfolio(name)
    except Exception as e:
        profile["patents"] = {"error": str(e)}

    # Get grant data
    try:
        profile["grants"] = get_funding_summary(name)
    except Exception as e:
        profile["grants"] = {"error": str(e)}

    # Get affiliated researchers
    try:
        researchers = execute_query("researchers", f"""
            SELECT id, name, h_index, slope, primary_category
            FROM researchers
            WHERE affiliations LIKE '%{name}%'
            ORDER BY h_index DESC
            LIMIT 10
        """)
        profile["researchers"] = {
            "top_researchers": researchers.get("rows", []),
            "count": len(researchers.get("rows", []))
        }
    except Exception as e:
        profile["researchers"] = {"error": str(e)}

    profile["_context"] = {
        "insight": f"360-degree view of {name} across patents, grants, and researchers"
    }
    return profile


# =============================================================================
# SCHEMA DOCS - Business context for raw SQL queries
# =============================================================================

def get_schema_docs(db_name: str) -> list:
    """Get schema documentation from _schema_docs table for a database."""
    cache_key = _cache_key(db_name, "_schema_docs_all")
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        result = execute_query(db_name, """
            SELECT table_name, description, key_columns, business_context, example_questions
            FROM _schema_docs
            ORDER BY table_name
        """)
        docs = result.get("rows", [])
        _set_cached(cache_key, docs)
        return docs
    except Exception:
        return []


def get_all_schema_context() -> dict:
    """Get schema docs from all databases for agent context injection."""
    all_docs = {}
    for db_name in ["researchers", "patents", "grants"]:
        docs = get_schema_docs(db_name)
        if docs:
            all_docs[db_name] = docs

    # SEC schema docs via HTTP
    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(
                f"{SEC_SENTINEL_URL}/api/sql",
                json={"query": "SELECT table_name, description, key_columns, business_context FROM _schema_docs"},
                headers={"Content-Type": "application/json"}
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("rows"):
                    all_docs["sec_sentinel"] = data["rows"]
    except Exception:
        pass

    return all_docs


# =============================================================================
# TEMPORAL CONTEXT - Recent changes across all databases
# =============================================================================

def get_recent_changes(days: int = 7) -> dict:
    """Check each database for recently added/updated records."""
    results = {
        "period": f"last {days} days",
        "databases": {},
        "_context": {
            "insight": f"Summary of new data across all databases in the last {days} days"
        }
    }

    # SEC Sentinel - recent filings
    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(
                f"{SEC_SENTINEL_URL}/api/filings",
                params={"days": days, "limit": 5}
            )
            if response.status_code == 200:
                filings = response.json()
                filing_count_resp = client.get(
                    f"{SEC_SENTINEL_URL}/api/stats"
                )
                stats = filing_count_resp.json() if filing_count_resp.status_code == 200 else {}
                results["databases"]["sec_sentinel"] = {
                    "recent_filings": len(filings),
                    "total_filings_week": stats.get("total", 0),
                    "sample": [
                        {
                            "ticker": f.get("ticker"),
                            "form_type": f.get("form_type"),
                            "filing_date": f.get("filing_date"),
                            "company_name": f.get("company_name")
                        }
                        for f in filings[:3]
                    ] if filings else []
                }
    except Exception as e:
        results["databases"]["sec_sentinel"] = {"error": str(e)}

    # Patents - recently granted
    try:
        result = execute_query("patents", f"""
            SELECT COUNT(*) as count,
                   MAX(grant_date) as latest_date
            FROM patents
            WHERE grant_date >= date('now', '-{int(days)} days')
        """)
        if result.get("rows"):
            row = result["rows"][0]
            results["databases"]["patents"] = {
                "new_patents": row.get("count", 0),
                "latest_date": row.get("latest_date")
            }

            if row.get("count", 0) > 0:
                sample = execute_query("patents", f"""
                    SELECT id, title, primary_assignee, grant_date
                    FROM patents
                    WHERE grant_date >= date('now', '-{int(days)} days')
                    ORDER BY grant_date DESC LIMIT 3
                """)
                results["databases"]["patents"]["sample"] = sample.get("rows", [])
    except Exception:
        results["databases"]["patents"] = {"new_patents": 0}

    # Grants - recently awarded
    try:
        result = execute_query("grants", f"""
            SELECT COUNT(*) as count,
                   MAX(award_notice_date) as latest_date,
                   SUM(total_cost) as total_new_funding
            FROM grants
            WHERE award_notice_date >= date('now', '-{int(days)} days')
        """)
        if result.get("rows"):
            row = result["rows"][0]
            results["databases"]["grants"] = {
                "new_grants": row.get("count", 0),
                "latest_date": row.get("latest_date"),
                "total_new_funding": row.get("total_new_funding", 0)
            }
    except Exception:
        results["databases"]["grants"] = {"new_grants": 0}

    # Researchers - recently updated
    try:
        result = execute_query("researchers", """
            SELECT COUNT(*) as count FROM researchers
            WHERE updated_at >= date('now', '-7 days')
        """)
        if result.get("rows"):
            results["databases"]["researchers"] = {
                "recently_updated": result["rows"][0].get("count", 0)
            }
    except Exception:
        results["databases"]["researchers"] = {"recently_updated": 0}

    return results


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
