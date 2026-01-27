"""
Question router for Neo SQL agent.
Classifies questions into tiers to avoid unnecessary LLM calls.

Tier 1 (instant): Direct SQL lookups - stats, counts, simple filters
Tier 2 (fast): Parameterized queries - rising stars in X field, top N by metric
Tier 3 (full agent): Complex multi-DB reasoning requiring Claude
"""

import re
import json
from typing import Optional, Tuple, List

try:
    from db import execute_query, list_tables
except ImportError:
    from rag.db import execute_query, list_tables

# Service URLs for entity links (same as agent.py)
ENTITY_URLS = {
    "researchers": "https://kdttalentscout.up.railway.app/researcher",
    "patents": "https://patentwarrior.up.railway.app/patent",
    "grants": "https://grants-tracker-production.up.railway.app/grant",
    "policies": "https://policywatch.up.railway.app/bill",
    "portfolio": "https://web-production-a9d068.up.railway.app/company",
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

    # Table listings
    (r"what tables.*(researchers?|talent)", "researchers", None),  # Special: list_tables
    (r"what tables.*(patents?)", "patents", None),
    (r"what tables.*(grants?)", "grants", None),
    (r"what tables.*(portfolio)", "portfolio", None),
    (r"what tables.*(policies?|bills?)", "policies", None),
]

# Tier 2: Parameterized queries (fast, template-based)
TIER2_PATTERNS = [
    # Rising stars / hidden gems in a field
    (
        r"(rising stars?|hidden gems?|fast[- ]?growing).*(?:in|for|about) (?P<field>[a-zA-Z]+)",
        "researchers",
        lambda m: f"""
            SELECT name, h_index, slope, primary_category, affiliations
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
            SELECT name, h_index, slope, primary_category, affiliations
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
            SELECT title, patent_number, filing_date, assignee
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
            SELECT title, total_cost, institute, fiscal_year
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
            SELECT name, modality, competitive_advantage, indications
            FROM companies
            WHERE name LIKE '%{m.group('company')}%'
            LIMIT 1
        """
    ),
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

    # Tier 3: Complex question requiring full agent
    return (3, None)


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
    """
    tier, result = classify_question(question)

    if tier == 1:
        return {
            "tier": 1,
            "tier_name": "instant",
            "answer": result["answer"],
            "data": result["data"],
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
        return {
            "tier": 3,
            "tier_name": "agent",
            "needs_agent": True,
        }


if __name__ == "__main__":
    # Test the router
    test_questions = [
        "How many researchers are in the database?",
        "How many patents?",
        "What's the total grant funding?",
        "Who are the rising stars in immunology?",
        "Top 5 researchers in machine learning",
        "What grants are there for Parkinson's?",
        "For Epana, which researchers should we talk to?",  # Should be Tier 3
        "Compare patent landscapes across three portfolio companies",  # Tier 3
    ]

    for q in test_questions:
        result = route_question(q)
        print(f"\nQ: {q}")
        print(f"Tier: {result['tier']} ({result['tier_name']})")
        if not result["needs_agent"]:
            print(f"Answer: {result['answer'][:100]}...")
