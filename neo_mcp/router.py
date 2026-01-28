"""
Question router for Neo SQL agent.
Classifies questions into tiers to avoid unnecessary LLM calls.

Tier 1 (instant): Direct SQL lookups - stats, counts, simple filters
Tier 2 (fast): Parameterized queries - rising stars in X field, top N by metric
Tier 3 (full agent): Complex multi-DB reasoning requiring Claude

Router Improvements (v2):
- Keyword-based database routing
- Intent detection for better classification
- Cached aggregations with TTL
- Cross-database pattern support
- Clinical trials Tier 2 patterns
"""

import re
import json
import time
from typing import Optional, Tuple, List, Dict, Any

try:
    from db import execute_query, list_tables
except ImportError:
    from neo_mcp.db import execute_query, list_tables


# =============================================================================
# IMPROVEMENT 3: Keyword-based database routing
# =============================================================================
DB_KEYWORDS = {
    "researchers": [
        "researcher", "researchers", "scientist", "scientists", "professor",
        "h-index", "h_index", "hindex", "citations", "publications", "slope",
        "rising star", "hidden gem", "talent", "academic", "author", "kol"
    ],
    "patents": [
        "patent", "patents", "invention", "inventions", "assignee", "claims",
        "intellectual property", "ip", "patent number", "cpc"
    ],
    "grants": [
        "grant", "grants", "funding", "nih", "nsf", "r01", "award",
        "pi", "principal investigator", "fiscal year", "institute"
    ],
    "sec_sentinel": [
        "sec", "filing", "filings", "8-k", "10-k", "10-q", "s-1", "s-3",
        "form 4", "insider", "insider trading", "insider sell", "insider buy",
        "runway", "cash runway", "burn rate", "distress", "shelf registration",
        "ipo", "proxy", "13d", "13g", "activist"
    ],
    "market_data": [
        "trial", "trials", "clinical trial", "clinical trials", "phase",
        "recruiting", "sponsor", "fda", "drug", "intervention", "nct",
        "enrollment", "completed", "terminated", "suspended"
    ],
    "portfolio": [
        "portfolio", "company", "companies", "startup", "modality",
        "indication", "competitive advantage", "investment"
    ],
    "policies": [
        "bill", "bills", "policy", "policies", "legislation", "congress",
        "senate", "house", "law", "regulation"
    ],
}


def detect_databases(question: str) -> List[str]:
    """Detect which databases a question likely refers to."""
    question_lower = question.lower()
    detected = []

    for db, keywords in DB_KEYWORDS.items():
        for keyword in keywords:
            if keyword in question_lower:
                if db not in detected:
                    detected.append(db)
                break

    return detected


# =============================================================================
# IMPROVEMENT 4: Intent detection (regex-based, no LLM)
# =============================================================================
INTENT_PATTERNS = {
    "count": [
        r"how many", r"count of", r"number of", r"total (?:number|count)",
    ],
    "list": [
        r"list (?:all|the)?", r"show (?:me )?(?:all|the)?", r"what are",
        r"who are", r"find (?:all|the)?", r"get (?:all|the)?",
    ],
    "top_n": [
        r"top \d+", r"best \d+", r"highest \d+", r"largest \d+",
        r"most \w+", r"biggest",
    ],
    "compare": [
        r"compare", r"versus", r" vs\.?[ $]", r"difference between",
        r"how does .+ compare",
    ],
    "lookup": [
        r"what is", r"tell me about", r"info on", r"details (?:on|about|for)",
        r"who is", r"describe",
    ],
    "aggregate": [
        r"total", r"sum of", r"average", r"mean", r"median",
        r"by (?:status|phase|year|sponsor|category|field)",
    ],
    "filter": [
        r"where", r"with", r"that have", r"greater than", r"less than",
        r"more than", r"over \$?\d+", r"under \$?\d+", r"between",
    ],
    "cross_db": [
        r"and (?:also|their|any)", r"who .+ and .+ have",
        r"researchers .+ patents", r"researchers .+ trials",
        r"companies .+ patents", r"grants .+ trials",
        r"for each", r"across", r"both .+ and",
    ],
}


def detect_intent(question: str) -> List[str]:
    """Detect the intent(s) of a question using regex patterns."""
    question_lower = question.lower()
    intents = []

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, question_lower):
                if intent not in intents:
                    intents.append(intent)
                break

    return intents if intents else ["general"]


# =============================================================================
# IMPROVEMENT 5: Cached aggregations with TTL
# =============================================================================
AGGREGATION_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes

CACHED_AGGREGATIONS = {
    "trials_by_status": {
        "db": "market_data",
        "query": "SELECT status, COUNT(*) as count FROM clinical_trials GROUP BY status ORDER BY count DESC",
        "description": "Clinical trials count by status",
    },
    "trials_by_phase": {
        "db": "market_data",
        "query": "SELECT phase, COUNT(*) as count FROM clinical_trials GROUP BY phase ORDER BY count DESC",
        "description": "Clinical trials count by phase",
    },
    "trials_by_sponsor": {
        "db": "market_data",
        "query": "SELECT sponsor, COUNT(*) as count FROM clinical_trials GROUP BY sponsor ORDER BY count DESC LIMIT 20",
        "description": "Top 20 sponsors by trial count",
    },
    "grants_by_institute": {
        "db": "grants",
        "query": "SELECT institute, COUNT(*) as count, SUM(total_cost) as total_funding FROM grants GROUP BY institute ORDER BY total_funding DESC LIMIT 20",
        "description": "Top 20 institutes by grant funding",
    },
    "researchers_by_category": {
        "db": "researchers",
        "query": "SELECT primary_category, COUNT(*) as count, AVG(h_index) as avg_h_index FROM researchers GROUP BY primary_category ORDER BY count DESC LIMIT 20",
        "description": "Top 20 research categories",
    },
}


def get_cached_aggregation(key: str) -> Optional[Dict]:
    """Get a cached aggregation if it exists and is not expired."""
    if key in AGGREGATION_CACHE:
        cached = AGGREGATION_CACHE[key]
        if time.time() - cached["timestamp"] < CACHE_TTL_SECONDS:
            return cached["data"]
    return None


def set_cached_aggregation(key: str, data: Dict) -> None:
    """Cache an aggregation result."""
    AGGREGATION_CACHE[key] = {
        "data": data,
        "timestamp": time.time(),
    }

# Service URLs for entity links (same as agent.py)
ENTITY_URLS = {
    "researchers": "https://kdttalentscout.up.railway.app/researcher",
    "patents": "https://patentwarrior.up.railway.app/patent",
    "grants": "https://grants-tracker-production.up.railway.app/grant",
    "policies": "https://policywatch.up.railway.app/bill",
    "portfolio": "https://web-production-a9d068.up.railway.app/company",
    "market_data": "https://clinicaltrials.gov/study",  # Links to ClinicalTrials.gov
}


def extract_entities_from_rows(db: str, rows: list) -> List[dict]:
    """Extract linkable entities from query result rows."""
    entities = []
    base_url = ENTITY_URLS.get(db, "")

    for row in rows[:10]:  # Limit to first 10
        entity = None

        if db == "researchers":
            if row.get("id") and row.get("name"):
                entity = {
                    "type": "researcher",
                    "id": row["id"],
                    "name": row["name"],
                    "url": f"{base_url}/{row['id']}",
                    "meta": f"h-index: {row.get('h_index', '?')}"
                }
        elif db == "patents":
            patent_id = row.get("id") or row.get("patent_id")
            if patent_id:
                title = row.get("title", "Untitled Patent")
                entity = {
                    "type": "patent",
                    "id": patent_id,
                    "name": title[:60] + "..." if len(title) > 60 else title,
                    "url": f"{base_url}/{patent_id}",
                    "meta": row.get("patent_number", "")
                }
        elif db == "grants":
            grant_id = row.get("id") or row.get("grant_id")
            if grant_id:
                title = row.get("title", "Untitled Grant")
                entity = {
                    "type": "grant",
                    "id": grant_id,
                    "name": title[:60] + "..." if len(title) > 60 else title,
                    "url": f"{base_url}/{grant_id}",
                    "meta": f"${row.get('total_cost', 0):,.0f}" if row.get('total_cost') else ""
                }
        elif db == "policies":
            bill_id = row.get("id") or row.get("bill_id")
            if bill_id:
                title = row.get("title", "Untitled Bill")
                entity = {
                    "type": "policy",
                    "id": bill_id,
                    "name": title[:60] + "..." if len(title) > 60 else title,
                    "url": f"{base_url}/{bill_id}",
                    "meta": row.get("status", "")
                }
        elif db == "portfolio":
            company_id = row.get("id") or row.get("company_id")
            if company_id:
                entity = {
                    "type": "company",
                    "id": company_id,
                    "name": row.get("name", "Unknown"),
                    "url": f"{base_url}/{company_id}",
                    "meta": row.get("modality", "")
                }

        elif db == "market_data":
            nct_id = row.get("nct_id")
            if nct_id:
                title = row.get("title", "Untitled Trial")
                entity = {
                    "type": "clinical_trial",
                    "id": nct_id,
                    "name": title[:50] + "..." if len(title) > 50 else title,
                    "url": f"{base_url}/{nct_id}",
                    "meta": f"{row.get('status', '')} | {row.get('phase', '')}"
                }

        if entity:
            entities.append(entity)

    return entities


# Tier 1: Direct lookups (instant, no LLM)
TIER1_PATTERNS = [
    # Database stats
    (r"how many (researchers?|scientists?)", "researchers", "SELECT COUNT(*) as count FROM researchers"),
    (r"how many patents?", "patents", "SELECT COUNT(*) as count FROM patents"),
    (r"how many grants?", "grants", "SELECT COUNT(*) as count FROM grants"),
    (r"how many (companies|portfolio)", "portfolio", "SELECT COUNT(*) as count FROM companies"),
    (r"how many (bills?|policies?)", "policies", "SELECT COUNT(*) as count FROM bills"),

    # Total funding
    (r"total (grant )?funding", "grants", "SELECT SUM(total_cost) as total_funding FROM grants WHERE total_cost > 0"),

    # Hidden gems count
    (r"how many hidden gems?", "researchers", "SELECT COUNT(*) as count FROM researchers WHERE slope > 3 AND h_index BETWEEN 20 AND 60"),

    # Clinical trials stats
    (r"how many (clinical )?trials?", "market_data", "SELECT COUNT(*) as count FROM clinical_trials"),
    (r"how many recruiting trials?", "market_data", "SELECT COUNT(*) as count FROM clinical_trials WHERE status = 'RECRUITING'"),
    (r"how many phase ?3 trials?", "market_data", "SELECT COUNT(*) as count FROM clinical_trials WHERE phase LIKE '%PHASE3%'"),
    (r"how many completed trials?", "market_data", "SELECT COUNT(*) as count FROM clinical_trials WHERE status = 'COMPLETED'"),
    (r"trials? by status", "market_data", "SELECT status, COUNT(*) as count FROM clinical_trials GROUP BY status ORDER BY count DESC"),
    (r"trials? by phase", "market_data", "SELECT phase, COUNT(*) as count FROM clinical_trials GROUP BY phase ORDER BY count DESC"),
    (r"top sponsors?", "market_data", "SELECT sponsor, COUNT(*) as count FROM clinical_trials GROUP BY sponsor ORDER BY count DESC LIMIT 20"),

    # Table listings
    (r"what tables.*(researchers?|talent)", "researchers", None),  # Special: list_tables
    (r"what tables.*(patents?)", "patents", None),
    (r"what tables.*(grants?)", "grants", None),
    (r"what tables.*(portfolio)", "portfolio", None),
    (r"what tables.*(policies?|bills?)", "policies", None),
    (r"what tables.*(trials?|market|clinical)", "market_data", None),
]

# Tier 2: Parameterized queries (fast, template-based)
# NOTE: All queries MUST include 'id' column for entity linking
TIER2_PATTERNS = [
    # Rising stars / hidden gems in a field
    (
        r"(rising stars?|hidden gems?|fast[- ]?growing).*(?:in|for|about) (?P<field>[a-zA-Z]+)",
        "researchers",
        lambda m: f"""
            SELECT id, name, h_index, slope, primary_category, affiliations
            FROM researchers
            WHERE slope > 3 AND h_index BETWEEN 20 AND 60
              AND (topics LIKE '%{m.group('field')}%' OR primary_category LIKE '%{m.group('field')}%')
            ORDER BY slope DESC LIMIT 10
        """
    ),

    # Top researchers by h-index in a field
    (
        r"top (?P<n>\d+)? ?researchers?.*(?:in|for|about) (?P<field>[a-zA-Z]+)",
        "researchers",
        lambda m: f"""
            SELECT id, name, h_index, slope, primary_category, affiliations
            FROM researchers
            WHERE topics LIKE '%{m.group('field')}%' OR primary_category LIKE '%{m.group('field')}%'
            ORDER BY h_index DESC LIMIT {m.group('n') or 10}
        """
    ),

    # Recent patents for a company
    (
        r"patents?.*(for |from |by )?(?P<company>\w+)",
        "patents",
        lambda m: f"""
            SELECT id, title, patent_number, filing_date, assignee
            FROM patents
            WHERE assignee LIKE '%{m.group('company')}%' OR title LIKE '%{m.group('company')}%'
            ORDER BY filing_date DESC LIMIT 10
        """
    ),

    # Grants in a field
    (
        r"grants?.*(in |for |about )?(?P<field>\w+)",
        "grants",
        lambda m: f"""
            SELECT id, title, total_cost, institute, fiscal_year
            FROM grants
            WHERE title LIKE '%{m.group('field')}%' OR abstract LIKE '%{m.group('field')}%'
            ORDER BY total_cost DESC LIMIT 10
        """
    ),

    # Portfolio company info
    (
        r"(what is|tell me about|info on) (?P<company>\w+)",
        "portfolio",
        lambda m: f"""
            SELECT id, name, modality, competitive_advantage, indications
            FROM companies
            WHERE name LIKE '%{m.group('company')}%'
            LIMIT 1
        """
    ),

    # =============================================================================
    # IMPROVEMENT 1: Clinical trials Tier 2 patterns
    # =============================================================================
    # Trials for a condition/disease
    (
        r"(?:clinical )?trials? (?:for|treating|in) (?P<condition>[a-zA-Z\s]+?)(?:\?|$|,| and)",
        "market_data",
        lambda m: f"""
            SELECT id, nct_id, title, status, phase, sponsor, start_date
            FROM clinical_trials
            WHERE (title LIKE '%{m.group('condition').strip()}%'
                   OR conditions LIKE '%{m.group('condition').strip()}%')
            ORDER BY start_date DESC LIMIT 15
        """
    ),

    # Trials by a sponsor
    (
        r"(?P<sponsor>\w+(?:\s+\w+)?)'?s? (?:clinical )?trials?",
        "market_data",
        lambda m: f"""
            SELECT id, nct_id, title, status, phase, conditions, start_date
            FROM clinical_trials
            WHERE sponsor LIKE '%{m.group('sponsor').strip()}%'
            ORDER BY start_date DESC LIMIT 15
        """
    ),

    # Recruiting trials in a field
    (
        r"recruiting (?:clinical )?trials? (?:for|in|treating) (?P<field>[a-zA-Z\s]+)",
        "market_data",
        lambda m: f"""
            SELECT id, nct_id, title, phase, sponsor, enrollment, start_date
            FROM clinical_trials
            WHERE status = 'RECRUITING'
              AND (title LIKE '%{m.group('field').strip()}%'
                   OR conditions LIKE '%{m.group('field').strip()}%')
            ORDER BY enrollment DESC LIMIT 15
        """
    ),

    # Phase N trials for a condition
    (
        r"phase ?(?P<phase>\d) (?:clinical )?trials? (?:for|in|treating) (?P<condition>[a-zA-Z\s]+)",
        "market_data",
        lambda m: f"""
            SELECT id, nct_id, title, status, sponsor, enrollment, start_date
            FROM clinical_trials
            WHERE phase LIKE '%PHASE{m.group('phase')}%'
              AND (title LIKE '%{m.group('condition').strip()}%'
                   OR conditions LIKE '%{m.group('condition').strip()}%')
            ORDER BY start_date DESC LIMIT 15
        """
    ),

    # Top sponsors by trial count
    (
        r"top (?P<n>\d+)? ?sponsors? (?:by|with) (?:most )?trials?",
        "market_data",
        lambda m: f"""
            SELECT sponsor, COUNT(*) as trial_count,
                   SUM(CASE WHEN status = 'RECRUITING' THEN 1 ELSE 0 END) as recruiting
            FROM clinical_trials
            GROUP BY sponsor
            ORDER BY trial_count DESC
            LIMIT {m.group('n') or 10}
        """
    ),

    # Trials starting/posted in a year
    (
        r"(?:clinical )?trials? (?:started|posted|from|in) (?P<year>20\d{2})",
        "market_data",
        lambda m: f"""
            SELECT id, nct_id, title, status, phase, sponsor
            FROM clinical_trials
            WHERE start_date LIKE '{m.group('year')}%'
            ORDER BY start_date DESC LIMIT 20
        """
    ),
]


# =============================================================================
# IMPROVEMENT 2: Cross-database patterns
# These require multiple DB queries and light processing
# =============================================================================
CROSS_DB_PATTERNS = [
    # Researchers with patents
    {
        "pattern": r"researchers? (?:with|who have) patents?",
        "queries": [
            ("researchers", "SELECT id, name, h_index, affiliations FROM researchers ORDER BY h_index DESC LIMIT 50"),
            ("patents", "SELECT assignee, COUNT(*) as patent_count FROM patents GROUP BY assignee"),
        ],
        "join_hint": "Match researcher affiliations with patent assignees",
    },
    # Trials by companies in our portfolio
    {
        "pattern": r"(?:clinical )?trials? (?:by|from|for) (?:our )?portfolio (?:companies)?",
        "queries": [
            ("portfolio", "SELECT id, name FROM companies"),
            ("market_data", "SELECT sponsor, COUNT(*) as trial_count, SUM(CASE WHEN status='RECRUITING' THEN 1 ELSE 0 END) as recruiting FROM clinical_trials GROUP BY sponsor"),
        ],
        "join_hint": "Match portfolio company names with trial sponsors",
    },
    # Grants related to active trials
    {
        "pattern": r"grants? (?:related to|for|in) (?:active|recruiting) (?:clinical )?trials?",
        "queries": [
            ("market_data", "SELECT DISTINCT conditions FROM clinical_trials WHERE status = 'RECRUITING' LIMIT 100"),
            ("grants", "SELECT id, title, total_cost, institute FROM grants ORDER BY total_cost DESC LIMIT 100"),
        ],
        "join_hint": "Match trial conditions with grant research areas",
    },
]


def classify_question(question: str) -> Tuple[int, Optional[dict]]:
    """
    Classify a question into a tier.

    Returns:
        (tier, result_or_query_info)
        - Tier 1: (1, {"answer": "...", "data": {...}})
        - Tier 2: (2, {"db": "...", "query": "...", "field": "..."})
        - Tier 3: (3, None) - needs full agent
    """
    question_lower = question.lower().strip()

    # Detect intent and databases for routing hints
    intents = detect_intent(question)
    detected_dbs = detect_databases(question)

    # Check for cached aggregations first (Improvement 5)
    for agg_key, agg_config in CACHED_AGGREGATIONS.items():
        # Match common aggregation queries
        if agg_key == "trials_by_status" and re.search(r"trials? by status", question_lower):
            cached = get_cached_aggregation(agg_key)
            if cached:
                return (1, cached)
            try:
                result = execute_query(agg_config["db"], agg_config["query"])
                if result["rows"]:
                    response = {
                        "answer": format_aggregation_response(result["rows"], agg_config["description"]),
                        "data": result["rows"],
                    }
                    set_cached_aggregation(agg_key, response)
                    return (1, response)
            except Exception:
                pass

        elif agg_key == "trials_by_phase" and re.search(r"trials? by phase", question_lower):
            cached = get_cached_aggregation(agg_key)
            if cached:
                return (1, cached)
            try:
                result = execute_query(agg_config["db"], agg_config["query"])
                if result["rows"]:
                    response = {
                        "answer": format_aggregation_response(result["rows"], agg_config["description"]),
                        "data": result["rows"],
                    }
                    set_cached_aggregation(agg_key, response)
                    return (1, response)
            except Exception:
                pass

        elif agg_key == "trials_by_sponsor" and re.search(r"top sponsors?", question_lower):
            cached = get_cached_aggregation(agg_key)
            if cached:
                return (1, cached)
            try:
                result = execute_query(agg_config["db"], agg_config["query"])
                if result["rows"]:
                    response = {
                        "answer": format_aggregation_response(result["rows"], agg_config["description"]),
                        "data": result["rows"],
                    }
                    set_cached_aggregation(agg_key, response)
                    return (1, response)
            except Exception:
                pass

    # Check Tier 1 patterns
    for pattern, db, query in TIER1_PATTERNS:
        if re.search(pattern, question_lower):
            if query is None:
                # Special case: list tables
                try:
                    tables = list_tables(db)
                    table_names = [t["name"] for t in tables]
                    return (1, {
                        "answer": f"Tables in {db} database: {', '.join(table_names)}",
                        "data": {"tables": table_names}
                    })
                except Exception as e:
                    return (3, None)  # Fall back to agent
            else:
                try:
                    result = execute_query(db, query)
                    if result["rows"]:
                        row = result["rows"][0]
                        value = list(row.values())[0]
                        key = list(row.keys())[0]

                        # Format nicely
                        if "funding" in key or "cost" in key:
                            formatted = f"${value:,.0f}" if value else "$0"
                        elif isinstance(value, (int, float)):
                            formatted = f"{value:,}"
                        else:
                            formatted = str(value)

                        return (1, {
                            "answer": f"{formatted}",
                            "data": row
                        })
                except Exception as e:
                    return (3, None)  # Fall back to agent

    # Check Tier 2 patterns
    for pattern, db, query_fn in TIER2_PATTERNS:
        match = re.search(pattern, question_lower)
        if match:
            try:
                query = query_fn(match)
                result = execute_query(db, query)

                if result["rows"]:
                    # Extract entities for linking
                    entities = extract_entities_from_rows(db, result["rows"])
                    return (2, {
                        "answer": format_tier2_response(result, db),
                        "data": result["rows"],
                        "query": query.strip(),
                        "entities": entities,
                    })
            except Exception as e:
                return (3, None)  # Fall back to agent

    # Check cross-database patterns (Improvement 2)
    if "cross_db" in intents or len(detected_dbs) > 1:
        for cross_pattern in CROSS_DB_PATTERNS:
            if re.search(cross_pattern["pattern"], question_lower):
                # For now, flag as Tier 3 with routing hints
                # Future: could execute both queries and do light joining
                return (3, {
                    "routing_hint": "cross_db",
                    "detected_dbs": detected_dbs,
                    "intents": intents,
                    "suggested_queries": cross_pattern["queries"],
                })

    # Tier 3: Complex question requiring full agent
    # Include routing hints for the agent
    return (3, {
        "routing_hint": "complex",
        "detected_dbs": detected_dbs,
        "intents": intents,
    } if detected_dbs or intents != ["general"] else None)


def format_aggregation_response(rows: list, description: str) -> str:
    """Format aggregation query results."""
    if not rows:
        return "No data found."

    lines = [f"**{description}**", ""]

    # Determine column headers from first row
    if rows:
        headers = list(rows[0].keys())
        header_line = "| " + " | ".join(h.replace("_", " ").title() for h in headers) + " |"
        separator = "|" + "|".join("-" * (len(h) + 2) for h in headers) + "|"
        lines.extend([header_line, separator])

        for row in rows[:15]:
            values = []
            for h in headers:
                val = row.get(h, "")
                if isinstance(val, (int, float)) and h in ("total_funding", "total_cost"):
                    val = f"${val:,.0f}"
                elif isinstance(val, float):
                    val = f"{val:.1f}"
                elif isinstance(val, int):
                    val = f"{val:,}"
                values.append(str(val)[:30])
            lines.append("| " + " | ".join(values) + " |")

    return "\n".join(lines)


def format_tier2_response(result: dict, db: str) -> str:
    """Format Tier 2 query results into a readable response."""
    rows = result["rows"]
    if not rows:
        return "No results found."

    if db == "researchers":
        lines = ["| Name | H-Index | Slope | Category |", "|------|---------|-------|----------|"]
        for r in rows[:10]:
            name = r.get("name", "?")[:30]
            h = r.get("h_index", "?")
            slope = r.get("slope", "?")
            cat = (r.get("primary_category") or "?")[:20]
            lines.append(f"| {name} | {h} | {slope} | {cat} |")
        return "\n".join(lines)

    elif db == "patents":
        lines = ["| Title | Patent # | Filing Date |", "|-------|----------|-------------|"]
        for r in rows[:10]:
            title = (r.get("title") or "?")[:40]
            num = r.get("patent_number", "?")
            date = r.get("filing_date", "?")
            lines.append(f"| {title} | {num} | {date} |")
        return "\n".join(lines)

    elif db == "grants":
        lines = ["| Title | Amount | Institute |", "|-------|--------|-----------|"]
        for r in rows[:10]:
            title = (r.get("title") or "?")[:40]
            cost = r.get("total_cost")
            amount = f"${cost:,.0f}" if cost else "?"
            inst = (r.get("institute") or "?")[:20]
            lines.append(f"| {title} | {amount} | {inst} |")
        return "\n".join(lines)

    elif db == "portfolio":
        r = rows[0]
        return f"""**{r.get('name', '?')}**
- Modality: {r.get('modality', '?')}
- Advantage: {r.get('competitive_advantage', '?')}
- Indications: {r.get('indications', '?')}"""

    elif db == "market_data":
        # Clinical trials formatting
        lines = ["| Title | Status | Phase | Sponsor |", "|-------|--------|-------|---------|"]
        for r in rows[:10]:
            title = (r.get("title") or "?")[:35]
            status = (r.get("status") or "?")[:12]
            phase = (r.get("phase") or "?")[:10]
            sponsor = (r.get("sponsor") or "?")[:20]
            lines.append(f"| {title} | {status} | {phase} | {sponsor} |")
        return "\n".join(lines)

    else:
        return json.dumps(rows[:5], indent=2)


def should_use_agent(question: str) -> bool:
    """Quick check if question requires full agent (Tier 3)."""
    tier, _ = classify_question(question)
    return tier == 3


def route_question(question: str) -> dict:
    """
    Route a question and return the appropriate response.

    Returns:
        dict with 'tier', 'answer', 'data', 'needs_agent'
        For Tier 3: may include 'routing_hints' with detected_dbs and intents
    """
    tier, result = classify_question(question)

    if tier == 1:
        return {
            "tier": 1,
            "tier_name": "instant",
            "answer": result["answer"],
            "data": result["data"],
            "entities": [],  # Tier 1 returns stats, not individual entities
            "needs_agent": False,
        }
    elif tier == 2:
        return {
            "tier": 2,
            "tier_name": "fast",
            "answer": result["answer"],
            "data": result["data"],
            "query": result.get("query"),
            "entities": result.get("entities", []),
            "needs_agent": False,
        }
    else:
        # Tier 3 - include routing hints if available
        response = {
            "tier": 3,
            "tier_name": "agent",
            "needs_agent": True,
        }
        if result:
            response["routing_hints"] = {
                "detected_dbs": result.get("detected_dbs", []),
                "intents": result.get("intents", []),
                "hint": result.get("routing_hint", "complex"),
            }
            if result.get("suggested_queries"):
                response["routing_hints"]["suggested_queries"] = result["suggested_queries"]
        return response


if __name__ == "__main__":
    # Test the router
    test_questions = [
        # Tier 1: Instant counts
        "How many researchers are in the database?",
        "How many patents?",
        "What's the total grant funding?",
        "How many clinical trials?",
        "How many recruiting trials?",
        "How many phase 3 trials?",

        # Tier 2: Parameterized queries
        "Who are the rising stars in immunology?",
        "Top 5 researchers in machine learning",
        "What grants are there for Parkinson's?",
        "Trials for cancer?",
        "Pfizer's clinical trials",
        "Recruiting trials for diabetes",
        "Phase 3 trials for Alzheimer's",

        # Tier 3: Complex / Cross-DB
        "For Epana, which researchers should we talk to?",  # Tier 3
        "Compare patent landscapes across three portfolio companies",  # Tier 3
        "Researchers with patents in oncology",  # Cross-DB
        "Trials by our portfolio companies",  # Cross-DB
    ]

    for q in test_questions:
        result = route_question(q)
        print(f"\nQ: {q}")
        print(f"Tier: {result['tier']} ({result['tier_name']})")
        if not result["needs_agent"]:
            print(f"Answer: {result['answer'][:100]}...")
        elif result.get("routing_hints"):
            print(f"Hints: DBs={result['routing_hints'].get('detected_dbs')}, Intents={result['routing_hints'].get('intents')}")
