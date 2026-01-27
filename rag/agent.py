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
    from db import execute_query, list_tables, describe_table
    from tools import TOOLS
    from router import route_question
    from semantic_cache import get_cached_response, cache_response
except ImportError:
    from rag.db import execute_query, list_tables, describe_table
    from rag.tools import TOOLS
    from rag.router import route_question
    from rag.semantic_cache import get_cached_response, cache_response


# System prompt for the SQL agent
AGENT_SYSTEM_PROMPT = """You are Neo, a senior biotech/deeptech analyst for KdT Ventures.

You have direct SQL access to 5 databases with live production data:

## DATABASE SCHEMAS & SIZES

### researchers (242,000 researchers, 2.6M h-index history records)
Tables:
- researchers: id, name, orcid, h_index, i10_index, works_count, cited_by_count, two_yr_citedness, slope (h-index growth rate), topics (JSON text), affiliations (JSON text), primary_category
- h_index_history: researcher_id, year, h_index
- topic_categories: topic_name, category
- hidden_gems: 2,000 pre-computed "hidden gem" researchers (slope > 3, h_index 20-60) - USE THIS for rising star queries!

KEY INDEXES: h_index, slope, primary_category, name
For "rising stars" or "hidden gems": Query hidden_gems table first (instant), or ORDER BY slope DESC
For topics: WHERE topics LIKE '%keyword%' (it's JSON stored as text)

### patents (2,400 patents, 24 portfolio companies)
Tables:
- patents: id, patent_number, title, abstract, filing_date, assignee
- inventors: patent_id, name, sequence
- cpc_classifications: patent_id, full_code, is_primary
- portfolio_companies: id, name, modality, keywords (JSON), indications (JSON)
- patent_company_relevance: patent_id, company_id, relevance_score, match_reasons

### grants (392,000 grants, $222B total funding, 557K PIs)
Tables:
- grants: id, project_number, title, abstract, institute, mechanism, total_cost, fiscal_year, source
- principal_investigators: grant_id, name, orcid, role
- portfolio_companies: id, name, modality, keywords, indications
- grant_company_relevance: grant_id, company_id, relevance_score

KEY INDEXES: total_cost, fiscal_year, institute, mechanism, source
For large grants: WHERE total_cost > 1000000 ORDER BY total_cost DESC

### policies (28 bills tracked)
Tables:
- bills: id, title, summary, status
- analyses: bill_id, analysis_text
- sectors: id, name

### portfolio (24 companies)
Tables:
- companies: id, name, ticker, modality, competitive_advantage, indications, fund
- updates: company_id, title, content, published_at
- raw_emails: id, subject, body, received_at

## PORTFOLIO COMPANIES (Query portfolio_companies in patents/grants DBs)
Examples: Epana (T-cell Engager, CD38/CD19, autoimmune), Montara (mTOR, LRRK2, Parkinson's), Skeletalis (bone-targeting), etc.

## QUERY OPTIMIZATION RULES
1. ALWAYS use LIMIT (10-50) - these are large tables
2. Use indexed columns in WHERE/ORDER BY when possible
3. For text search: LIKE '%term%' works but is slow on large tables
4. For aggregations on large tables (grants), use specific filters first
5. If a query times out, simplify it or add more restrictive WHERE clauses

## CROSS-DATABASE WORKFLOW EXAMPLE
To find researchers for a portfolio company:
1. Query portfolio_companies to get company focus (modality, indications, keywords)
2. Query researchers WHERE topics LIKE '%relevant_term%' ORDER BY h_index DESC
3. Optionally cross-reference with grants by PI name

## Response Style
- Lead with the key finding/recommendation
- Support with specific numbers from queries
- Use markdown tables for structured data (| Column | Column |)
- Use headers (## and ###) to organize sections
- End with actionable next steps

## IMPORTANT: Source References
When citing data from queries, use numbered references like [1], [2], etc.
At the END of your response, include a "---" separator followed by a Sources section:

---
**Sources:**
[1] researchers: Top T-cell researchers by h-index
[2] grants: NIH funding for autoimmune research
[3] patents: Recent bispecific antibody filings

This helps users verify where the information came from.

Be DIRECT. Execute queries efficiently. Synthesize insights across databases."""


# Default model for SQL agent (Sonnet for balance of quality/cost)
DEFAULT_MODEL = os.environ.get("NEO_AGENT_MODEL", "claude-sonnet-4-20250514")
MAX_TURNS = int(os.environ.get("NEO_MAX_TURNS", "25"))


def execute_tool(tool_name: str, tool_input: dict, insights: list) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if tool_name == "query_researchers":
            result = execute_query("researchers", tool_input["query"])
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "query_patents":
            result = execute_query("patents", tool_input["query"])
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "query_grants":
            result = execute_query("grants", tool_input["query"])
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "query_policies":
            result = execute_query("policies", tool_input["query"])
            return json.dumps(result, indent=2, default=str)

        elif tool_name == "query_portfolio":
            result = execute_query("portfolio", tool_input["query"])
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

    # Track tool calls and insights
    all_tool_calls = []
    insights = []
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

            # Cache successful response for future similar questions
            if not skip_cache and not conversation_history and final_text:
                cache_response(question, final_text, all_tool_calls, insights)

            return {
                "answer": final_text,
                "tool_calls": all_tool_calls,
                "insights": insights,
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
                    result = execute_tool(tool_name, tool_input, insights)

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
                "model": model,
                "turns_used": turns_used,
            }

    # Exceeded max turns
    return {
        "answer": "I've reached the maximum number of analysis steps. Here's what I found so far based on my queries.",
        "tool_calls": all_tool_calls,
        "insights": insights,
        "model": model,
        "turns_used": turns_used,
        "warning": "max_turns_exceeded"
    }


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
