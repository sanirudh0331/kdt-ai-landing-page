"""
Neo SQL Agent - Agentic loop with Claude tool use.
This replicates the MCP experience: Claude reasons, calls tools, analyzes results, repeats.

Now with:
- Question routing (Tier 1/2/3) to skip LLM for simple queries
- Semantic caching to reuse similar question answers
"""

import os
import json
from typing import Optional

import anthropic

try:
    from db import (
        execute_query, list_tables, describe_table,
        # Semantic functions - Researchers
        get_researchers, get_researcher_profile, get_rising_stars, get_researchers_by_topic,
        # Semantic functions - Patents
        get_patents, get_patent_portfolio, get_inventors_by_company, search_patents_by_topic,
        # Semantic functions - Grants
        get_grants, get_funding_summary, get_pis_by_organization, get_grants_by_topic,
        # Cross-database
        search_entity, get_company_profile,
        # SEC Sentinel
        get_sec_filings, get_companies_by_runway, get_insider_transactions, get_runway_alerts
    )
    from tools import TOOLS
    from router import route_question
    from semantic_cache import get_cached_response, cache_response
except ImportError:
    from neo_mcp.db import (
        execute_query, list_tables, describe_table,
        get_researchers, get_researcher_profile, get_rising_stars, get_researchers_by_topic,
        get_patents, get_patent_portfolio, get_inventors_by_company, search_patents_by_topic,
        get_grants, get_funding_summary, get_pis_by_organization, get_grants_by_topic,
        search_entity, get_company_profile,
        get_sec_filings, get_companies_by_runway, get_insider_transactions, get_runway_alerts
    )
    from neo_mcp.tools import TOOLS
    from neo_mcp.router import route_question
    from neo_mcp.semantic_cache import get_cached_response, cache_response


# System prompt for the SQL agent
AGENT_SYSTEM_PROMPT = """You are Neo, a senior biotech/deeptech analyst for KdT Ventures.

You have access to 6 databases with live production data via both **semantic functions** (preferred) and raw SQL.

## TOOL PRIORITY
**PREFER semantic functions** over raw SQL. They are faster, more accurate, and include business context:

### SEC Sentinel Functions
- `get_sec_filings(ticker, form_type, days, runway_status)` - Search SEC filings with runway context
- `get_companies_by_runway(max_months, min_months, limit)` - Find companies by cash runway
- `get_insider_transactions(ticker, insider_role, transaction_type, days, min_value)` - Insider trading data
- `get_runway_alerts()` - Distress signals: critical runway + S-3 filings + insider sells

### Researcher Functions
- `get_researchers(min_h_index, topic, affiliation, limit)` - Find researchers with filters
- `get_researcher_profile(name)` - Detailed profile with trajectory analysis
- `get_rising_stars(min_slope, min_h_index, max_h_index, topic, limit)` - Fast-growing researchers
- `get_researchers_by_topic(topic, limit)` - Top researchers in a field

### Patent Functions
- `get_patents(assignee, inventor, cpc_code, days, keyword, limit)` - Search patents
- `get_patent_portfolio(assignee)` - Company patent portfolio summary
- `get_inventors_by_company(assignee, limit)` - Key inventors at a company
- `search_patents_by_topic(keywords, limit)` - Patent landscape search

### Grant Functions
- `get_grants(organization, pi_name, mechanism, min_amount, institute, keyword, limit)` - Search grants
- `get_funding_summary(organization)` - Org funding overview with breakdown
- `get_pis_by_organization(organization, limit)` - Top-funded PIs at institution
- `get_grants_by_topic(keywords, limit)` - Funding landscape search

### Cross-Database Functions
- `search_entity(name)` - Find entity across ALL databases at once
- `get_company_profile(name)` - 360° view: patents + grants + researchers

### Raw SQL (use when semantic functions don't cover the query)
- `query_researchers(query)` - Direct SQL against researchers DB
- `query_patents(query)` - Direct SQL against patents DB
- `query_grants(query)` - Direct SQL against grants DB
- `query_policies(query)` - Direct SQL against policies DB
- `query_portfolio(query)` - Direct SQL against portfolio DB
- `query_market_data(query)` - Direct SQL against clinical trials / FDA DB
- `list_tables(database)` - List tables in a database
- `describe_table(database, table_name)` - Get table schema

### Utility
- `append_insight(insight)` - Record a key finding

## DATABASE SIZES
- researchers: 242,000 researchers, 2.6M h-index history records
- patents: 2,400 patents, 24 portfolio companies
- grants: 392,000 grants, $222B total funding, 557K PIs
- policies: 28 bills tracked
- portfolio: 24 companies
- market_data: 89,000 clinical trials

## RAW SQL SCHEMA REFERENCE (for raw SQL queries only)

### researchers
- researchers: id, name, orcid, h_index, i10_index, works_count, cited_by_count, two_yr_citedness, slope, topics (JSON), affiliations (JSON), primary_category
- h_index_history: researcher_id, year, h_index
- hidden_gems: pre-computed rising stars

### patents
- patents: id, patent_number, title, abstract, grant_date, filing_date, primary_assignee, cpc_codes, claims_count
- inventors: patent_id, name, sequence
- assignees: patent_id, name, type
- cpc_classifications: patent_id, full_code, is_primary

### grants
- grants: id, title, abstract, agency, institute, mechanism, total_cost, start_date, end_date, fiscal_year, organization, source
- principal_investigators: grant_id, name, orcid, role, organization
- entity_links: canonical_name, sec_ticker, patent_assignee_name, grant_org_name, aliases (JSON)

### policies
- bills: id, title, summary, status
- analyses: bill_id, analysis_text

### portfolio
- companies: id, name, ticker, modality, competitive_advantage, indications, fund
- updates: company_id, title, content, published_at

### market_data
- clinical_trials: id, nct_id, brief_title, status, phase, conditions (JSON), interventions (JSON), sponsor, enrollment, start_date
- fda_events: id, event_type, ticker, company, drug, indication, event_date

## SYNTHESIS & RESPONSE GUIDELINES
When presenting data to users:
1. **Lead with the key insight**, not raw numbers
2. **Explain what numbers mean** ("h-index of 85 puts them in the top 0.1% of researchers globally")
3. **Connect related findings** ("This researcher leads NIH-funded work AND holds key patents - complete innovation pipeline")
4. **Highlight unusual patterns** ("3 of the top 5 gene therapy patents were filed by university labs, not pharma - suggests early-stage tech")
5. **Cross-database synthesis** when relevant ("Moderna has 45 mRNA patents AND $120M in NIH grants - deep investment in this platform")
6. For cross-DB questions, use `search_entity` or `get_company_profile` first

## QUERY OPTIMIZATION
1. ALWAYS include `id` in SELECT for entity queries (enables clickable source links)
2. Use LIMIT (10-50) on all queries
3. Prefer semantic functions - they handle joins and indexing automatically
4. Only use raw SQL for queries not covered by semantic functions

## PORTFOLIO COMPANIES (Query portfolio_companies in patents/grants DBs)
Examples: Epana (T-cell Engager, CD38/CD19, autoimmune), Montara (mTOR, LRRK2, Parkinson's), Skeletalis (bone-targeting), etc.

Be DIRECT. Execute queries efficiently. Synthesize insights across databases.

NOTE: Do NOT include a Sources section - the system will automatically generate clickable source links from your query results."""


# Default model for SQL agent (Sonnet for balance of quality/cost)
DEFAULT_MODEL = os.environ.get("NEO_AGENT_MODEL", "claude-sonnet-4-20250514")
MAX_TURNS = int(os.environ.get("NEO_MAX_TURNS", "25"))

# Service URLs for entity links
ENTITY_URLS = {
    "researchers": "https://kdttalentscout.up.railway.app/researcher",
    "patents": "https://patentwarrior.up.railway.app/patent",
    "grants": "https://grants-tracker-production.up.railway.app/grant",
    "policies": "https://policywatch.up.railway.app/bill",
    "portfolio": "https://web-production-a9d068.up.railway.app/company",
}


def extract_entities(tool_name: str, result: dict) -> list:
    """Extract linkable entities from query results."""
    entities = []
    rows = result.get("rows", [])

    if not rows:
        return entities

    if tool_name == "query_researchers":
        for row in rows[:10]:  # Limit to first 10
            if row.get("id") and row.get("name"):
                entities.append({
                    "type": "researcher",
                    "id": row["id"],
                    "name": row["name"],
                    "url": f"{ENTITY_URLS['researchers']}/{row['id']}",
                    "meta": f"h-index: {row.get('h_index', '?')}"
                })

    elif tool_name == "query_patents":
        for row in rows[:10]:
            patent_id = row.get("id") or row.get("patent_id")
            title = row.get("title", "Untitled Patent")
            if patent_id:
                entities.append({
                    "type": "patent",
                    "id": patent_id,
                    "name": title[:60] + "..." if len(title) > 60 else title,
                    "url": f"{ENTITY_URLS['patents']}/{patent_id}",
                    "meta": row.get("patent_number", "")
                })

    elif tool_name == "query_grants":
        for row in rows[:10]:
            grant_id = row.get("id") or row.get("grant_id")
            title = row.get("title", "Untitled Grant")
            if grant_id:
                entities.append({
                    "type": "grant",
                    "id": grant_id,
                    "name": title[:60] + "..." if len(title) > 60 else title,
                    "url": f"{ENTITY_URLS['grants']}/{grant_id}",
                    "meta": f"${row.get('total_cost', 0):,.0f}" if row.get('total_cost') else ""
                })

    elif tool_name == "query_policies":
        for row in rows[:10]:
            bill_id = row.get("id") or row.get("bill_id")
            title = row.get("title", "Untitled Bill")
            if bill_id:
                entities.append({
                    "type": "policy",
                    "id": bill_id,
                    "name": title[:60] + "..." if len(title) > 60 else title,
                    "url": f"{ENTITY_URLS['policies']}/{bill_id}",
                    "meta": row.get("status", "")
                })

    elif tool_name == "query_portfolio":
        for row in rows[:10]:
            company_id = row.get("id") or row.get("company_id")
            name = row.get("name", "Unknown Company")
            if company_id:
                entities.append({
                    "type": "company",
                    "id": company_id,
                    "name": name,
                    "url": f"{ENTITY_URLS['portfolio']}/{company_id}",
                    "meta": row.get("modality", "")
                })

    return entities


def execute_tool(tool_name: str, tool_input: dict, insights: list, entities: list) -> str:
    """Execute a tool and return the result as a string."""
    try:
        # =================================================================
        # SEMANTIC FUNCTIONS - Researchers
        # =================================================================
        if tool_name == "get_researchers":
            result = get_researchers(**tool_input)
            entities.extend(extract_entities("query_researchers", result))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_researcher_profile":
            result = get_researcher_profile(**tool_input)
            entities.extend(extract_entities("query_researchers", result))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_rising_stars":
            result = get_rising_stars(**tool_input)
            entities.extend(extract_entities("query_researchers", result))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_researchers_by_topic":
            result = get_researchers_by_topic(**tool_input)
            entities.extend(extract_entities("query_researchers", result))
            return json.dumps(result, indent=2, default=str)

        # =================================================================
        # SEMANTIC FUNCTIONS - Patents
        # =================================================================
        elif tool_name == "get_patents":
            result = get_patents(**tool_input)
            entities.extend(extract_entities("query_patents", result))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_patent_portfolio":
            result = get_patent_portfolio(**tool_input)
            # Extract entities from the patents list
            if result.get("patents"):
                entities.extend(extract_entities("query_patents", {"rows": result["patents"]}))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_inventors_by_company":
            result = get_inventors_by_company(**tool_input)
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "search_patents_by_topic":
            result = search_patents_by_topic(**tool_input)
            entities.extend(extract_entities("query_patents", result))
            return json.dumps(result, indent=2, default=str)

        # =================================================================
        # SEMANTIC FUNCTIONS - Grants
        # =================================================================
        elif tool_name == "get_grants":
            result = get_grants(**tool_input)
            entities.extend(extract_entities("query_grants", result))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_funding_summary":
            result = get_funding_summary(**tool_input)
            # Extract entities from top_grants list
            if result.get("top_grants"):
                entities.extend(extract_entities("query_grants", {"rows": result["top_grants"]}))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_pis_by_organization":
            result = get_pis_by_organization(**tool_input)
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_grants_by_topic":
            result = get_grants_by_topic(**tool_input)
            entities.extend(extract_entities("query_grants", result))
            return json.dumps(result, indent=2, default=str)

        # =================================================================
        # CROSS-DATABASE FUNCTIONS
        # =================================================================
        elif tool_name == "search_entity":
            result = search_entity(**tool_input)
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_company_profile":
            result = get_company_profile(**tool_input)
            # Extract entities from nested results
            if result.get("patents") and result["patents"].get("patents"):
                entities.extend(extract_entities("query_patents", {"rows": result["patents"]["patents"]}))
            if result.get("grants") and result["grants"].get("top_grants"):
                entities.extend(extract_entities("query_grants", {"rows": result["grants"]["top_grants"]}))
            if result.get("researchers") and result["researchers"].get("top_researchers"):
                entities.extend(extract_entities("query_researchers", {"rows": result["researchers"]["top_researchers"]}))
            return json.dumps(result, indent=2, default=str)

        # =================================================================
        # SEMANTIC FUNCTIONS - SEC Sentinel
        # =================================================================
        elif tool_name == "get_sec_filings":
            result = get_sec_filings(**tool_input)
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_companies_by_runway":
            result = get_companies_by_runway(**tool_input)
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_insider_transactions":
            result = get_insider_transactions(**tool_input)
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "get_runway_alerts":
            result = get_runway_alerts()
            return json.dumps(result, indent=2, default=str)

        # =================================================================
        # RAW SQL TOOLS
        # =================================================================
        elif tool_name == "query_researchers":
            result = execute_query("researchers", tool_input["query"])
            entities.extend(extract_entities(tool_name, result))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "query_patents":
            result = execute_query("patents", tool_input["query"])
            entities.extend(extract_entities(tool_name, result))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "query_grants":
            result = execute_query("grants", tool_input["query"])
            entities.extend(extract_entities(tool_name, result))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "query_policies":
            result = execute_query("policies", tool_input["query"])
            entities.extend(extract_entities(tool_name, result))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "query_portfolio":
            result = execute_query("portfolio", tool_input["query"])
            entities.extend(extract_entities(tool_name, result))
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "query_market_data":
            result = execute_query("market_data", tool_input["query"])
            # No entity extraction for market_data (trials don't have detail pages yet)
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "list_tables":
            result = list_tables(tool_input["database"])
            return json.dumps(result, indent=2)

        elif tool_name == "describe_table":
            result = describe_table(tool_input["database"], tool_input["table_name"])
            return json.dumps(result, indent=2)

        elif tool_name == "append_insight":
            insights.append(tool_input["insight"])
            return json.dumps({"status": "insight recorded", "total_insights": len(insights)})

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    except Exception as e:
        return json.dumps({"error": str(e)})


def deduplicate_entities(entities: list) -> list:
    """Remove duplicate entities, keeping first occurrence."""
    seen = set()
    unique = []
    for entity in entities:
        key = (entity["type"], entity["id"])
        if key not in seen:
            seen.add(key)
            unique.append(entity)
    return unique


def run_agent(
    question: str,
    model: str = None,
    max_turns: int = None,
    conversation_history: list = None,
    skip_cache: bool = False,
    skip_router: bool = False,
) -> dict:
    """
    Run the Neo SQL agent to answer a question.

    Args:
        question: The user's question
        model: Claude model to use (default: claude-sonnet-4-20250514)
        max_turns: Maximum tool use iterations (default: 15)
        conversation_history: Optional previous messages for context
        skip_cache: Skip semantic cache lookup (default: False)
        skip_router: Skip question router, always use full agent (default: False)

    Returns:
        dict with 'answer', 'tool_calls', 'insights', 'model', 'turns_used'
    """
    # STEP 1: Check question router (Tier 1/2 questions don't need LLM)
    if not skip_router and not conversation_history:
        routed = route_question(question)
        if not routed["needs_agent"]:
            return {
                "answer": routed["answer"],
                "tool_calls": [],
                "insights": [],
                "entities": routed.get("entities", []),
                "model": None,
                "turns_used": 0,
                "tier": routed["tier"],
                "tier_name": routed["tier_name"],
                "routed": True,
            }

    # STEP 2: Check semantic cache for similar questions
    if not skip_cache and not conversation_history:
        cached = get_cached_response(question)
        if cached:
            return {
                "answer": cached["answer"],
                "tool_calls": cached.get("tool_calls", []),
                "insights": cached.get("insights", []),
                "entities": cached.get("entities", []),
                "model": None,
                "turns_used": 0,
                "cached": True,
                "similarity": cached.get("similarity"),
                "original_question": cached.get("original_question"),
            }

    # STEP 3: Full agent (Tier 3)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "answer": "Neo SQL agent is not configured. Please set ANTHROPIC_API_KEY.",
            "tool_calls": [],
            "insights": [],
            "model": None,
            "error": "missing_api_key"
        }

    model = model or DEFAULT_MODEL
    max_turns = max_turns or MAX_TURNS

    client = anthropic.Anthropic(api_key=api_key)

    # Build messages
    messages = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": question})

    # Track tool calls, insights, and entities
    all_tool_calls = []
    insights = []
    entities = []
    turns_used = 0

    # Agentic loop
    while turns_used < max_turns:
        turns_used += 1

        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=AGENT_SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.APIError as e:
            return {
                "answer": f"API error: {str(e)}",
                "tool_calls": all_tool_calls,
                "insights": insights,
                "model": model,
                "turns_used": turns_used,
                "error": "api_error"
            }

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Model is done - extract final text
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            # Deduplicate entities
            unique_entities = deduplicate_entities(entities)

            # Cache successful response for future similar questions
            if not skip_cache and not conversation_history and final_text:
                cache_response(question, final_text, all_tool_calls, insights, unique_entities)

            return {
                "answer": final_text,
                "tool_calls": all_tool_calls,
                "insights": insights,
                "entities": unique_entities,
                "model": model,
                "turns_used": turns_used,
                "tier": 3,
                "tier_name": "agent",
            }

        elif response.stop_reason == "tool_use":
            # Model wants to use tools
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    # Execute the tool
                    result = execute_tool(tool_name, tool_input, insights, entities)

                    # Track for debugging
                    all_tool_calls.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "result_preview": result[:500] if len(result) > 500 else result,
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result,
                    })

            # Add assistant response and tool results to messages
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            # Unexpected stop reason
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            return {
                "answer": final_text or f"Unexpected stop reason: {response.stop_reason}",
                "tool_calls": all_tool_calls,
                "insights": insights,
                "entities": deduplicate_entities(entities),
                "model": model,
                "turns_used": turns_used,
            }

    # Exceeded max turns
    return {
        "answer": "I've reached the maximum number of analysis steps. Here's what I found so far based on my queries.",
        "tool_calls": all_tool_calls,
        "insights": insights,
        "entities": deduplicate_entities(entities),
        "model": model,
        "turns_used": turns_used,
        "warning": "max_turns_exceeded"
    }


# Friendly status messages for each tool
TOOL_STATUS_MESSAGES = {
    # Semantic functions
    "get_researchers": "Finding researchers...",
    "get_researcher_profile": "Getting researcher profile...",
    "get_rising_stars": "Finding rising star researchers...",
    "get_researchers_by_topic": "Finding researchers by topic...",
    "get_patents": "Searching patents...",
    "get_patent_portfolio": "Analyzing patent portfolio...",
    "get_inventors_by_company": "Finding key inventors...",
    "search_patents_by_topic": "Searching patent landscape...",
    "get_grants": "Searching grants...",
    "get_funding_summary": "Analyzing funding...",
    "get_pis_by_organization": "Finding principal investigators...",
    "get_grants_by_topic": "Searching grant landscape...",
    "search_entity": "Searching across all databases...",
    "get_company_profile": "Building company profile...",
    # SEC Sentinel
    "get_sec_filings": "Searching SEC filings...",
    "get_companies_by_runway": "Checking company runway data...",
    "get_insider_transactions": "Searching insider transactions...",
    "get_runway_alerts": "Checking runway alerts...",
    # Raw SQL tools
    "query_researchers": "Querying researchers database...",
    "query_patents": "Querying patents database...",
    "query_grants": "Querying grants database...",
    "query_policies": "Querying policies database...",
    "query_portfolio": "Querying portfolio database...",
    "query_market_data": "Querying clinical trials database...",
    "list_tables": "Exploring database schema...",
    "describe_table": "Examining table structure...",
    "append_insight": "Recording insight...",
}


def run_agent_streaming(
    question: str,
    model: str = None,
    max_turns: int = None,
    conversation_history: list = None,
    skip_cache: bool = False,
    skip_router: bool = False,
):
    """
    Streaming version of run_agent that yields status updates.

    Yields:
        dict events: {"type": "status"|"tool"|"complete", ...}
    """
    # STEP 1: Check question router (Tier 1/2 questions don't need LLM)
    if not skip_router and not conversation_history:
        yield {"type": "status", "message": "Checking if I can answer instantly..."}
        routed = route_question(question)
        if not routed["needs_agent"]:
            yield {"type": "complete", "data": {
                "answer": routed["answer"],
                "tool_calls": [],
                "insights": [],
                "entities": routed.get("entities", []),
                "model": None,
                "turns_used": 0,
                "tier": routed["tier"],
                "tier_name": routed["tier_name"],
                "routed": True,
            }}
            return

    # STEP 2: Check semantic cache for similar questions
    if not skip_cache and not conversation_history:
        yield {"type": "status", "message": "Checking memory for similar questions..."}
        cached = get_cached_response(question)
        if cached:
            yield {"type": "complete", "data": {
                "answer": cached["answer"],
                "tool_calls": cached.get("tool_calls", []),
                "insights": cached.get("insights", []),
                "entities": cached.get("entities", []),
                "model": None,
                "turns_used": 0,
                "cached": True,
                "similarity": cached.get("similarity"),
                "original_question": cached.get("original_question"),
            }}
            return

    # STEP 3: Full agent (Tier 3)
    yield {"type": "status", "message": "Starting analysis..."}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield {"type": "complete", "data": {
            "answer": "Neo SQL agent is not configured. Please set ANTHROPIC_API_KEY.",
            "tool_calls": [],
            "insights": [],
            "model": None,
            "error": "missing_api_key"
        }}
        return

    model = model or DEFAULT_MODEL
    max_turns = max_turns or MAX_TURNS

    client = anthropic.Anthropic(api_key=api_key)

    # Build messages
    messages = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": question})

    # Track tool calls, insights, and entities
    all_tool_calls = []
    insights = []
    entities = []
    turns_used = 0

    # Agentic loop
    while turns_used < max_turns:
        turns_used += 1

        yield {"type": "status", "message": f"Thinking... (step {turns_used})"}

        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=AGENT_SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.APIError as e:
            yield {"type": "complete", "data": {
                "answer": f"API error: {str(e)}",
                "tool_calls": all_tool_calls,
                "insights": insights,
                "model": model,
                "turns_used": turns_used,
                "error": "api_error"
            }}
            return

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Model is done - extract final text
            yield {"type": "status", "message": "Composing response..."}

            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            # Deduplicate entities
            unique_entities = deduplicate_entities(entities)

            # Cache successful response for future similar questions
            if not skip_cache and not conversation_history and final_text:
                cache_response(question, final_text, all_tool_calls, insights, unique_entities)

            yield {"type": "complete", "data": {
                "answer": final_text,
                "tool_calls": all_tool_calls,
                "insights": insights,
                "entities": unique_entities,
                "model": model,
                "turns_used": turns_used,
                "tier": 3,
                "tier_name": "agent",
            }}
            return

        elif response.stop_reason == "tool_use":
            # Model wants to use tools
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    # Emit status update for this tool
                    status_msg = TOOL_STATUS_MESSAGES.get(tool_name, f"Running {tool_name}...")
                    yield {"type": "tool", "tool": tool_name, "message": status_msg}

                    # Execute the tool
                    result = execute_tool(tool_name, tool_input, insights, entities)

                    # Parse result to get row count for status
                    try:
                        result_data = json.loads(result)
                        if "rows" in result_data:
                            row_count = len(result_data["rows"])
                            yield {"type": "tool_result", "tool": tool_name, "rows": row_count}
                    except:
                        pass

                    # Track for debugging
                    all_tool_calls.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "result_preview": result[:500] if len(result) > 500 else result,
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result,
                    })

            # Add assistant response and tool results to messages
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            # Unexpected stop reason
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            yield {"type": "complete", "data": {
                "answer": final_text or f"Unexpected stop reason: {response.stop_reason}",
                "tool_calls": all_tool_calls,
                "insights": insights,
                "entities": deduplicate_entities(entities),
                "model": model,
                "turns_used": turns_used,
            }}
            return

    # Exceeded max turns
    yield {"type": "complete", "data": {
        "answer": "I've reached the maximum number of analysis steps. Here's what I found so far based on my queries.",
        "tool_calls": all_tool_calls,
        "insights": insights,
        "entities": deduplicate_entities(entities),
        "model": model,
        "turns_used": turns_used,
        "warning": "max_turns_exceeded"
    }}


if __name__ == "__main__":
    # Quick test
    import sys

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        question = "What tables are available in the researchers database?"

    print(f"\nQuestion: {question}\n")
    print("-" * 50)

    result = run_agent(question)

    print(f"\nAnswer:\n{result['answer']}")
    print(f"\n\nTool calls: {len(result['tool_calls'])}")
    print(f"Turns used: {result['turns_used']}")
    if result['insights']:
        print(f"\nInsights captured:")
        for i, insight in enumerate(result['insights'], 1):
            print(f"  {i}. {insight}")
