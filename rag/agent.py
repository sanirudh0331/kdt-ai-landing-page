"""
Neo SQL Agent - Agentic loop with Claude tool use.
This replicates the MCP experience: Claude reasons, calls tools, analyzes results, repeats.
"""

import os
import json
from typing import Optional

import anthropic

try:
    from db import execute_query, list_tables, describe_table
    from tools import TOOLS
except ImportError:
    from rag.db import execute_query, list_tables, describe_table
    from rag.tools import TOOLS


# System prompt for the SQL agent
AGENT_SYSTEM_PROMPT = """You are Neo, a senior biotech/deeptech analyst for KdT Ventures.

You have direct SQL access to 5 databases. Here are the key schemas:

## DATABASE SCHEMAS

### researchers (10,000 researchers)
- id, name, orcid, h_index, i10_index, works_count, cited_by_count
- two_yr_citedness, slope (h-index growth rate - KEY for "rising stars")
- topics (JSON), affiliations (JSON), primary_category
- Also: h_index_history table (researcher_id, year, h_index)

### patents
- patents: id, patent_number, title, abstract, grant_date, filing_date, patent_type, primary_assignee, cpc_codes, claims_count
- inventors: patent_id, name, sequence
- cpc_classifications: patent_id, section, class_code, subclass, full_code, is_primary
- portfolio_companies: id, name, modality, keywords, indications, cpc_codes
- patent_company_relevance: patent_id, company_id, relevance_score, match_reasons

### grants
- grants: id, project_number, title, abstract, agency, mechanism, total_cost, award_notice_date, project_start_date, project_end_date, organization_name, pi_name
- portfolio_companies: id, name, modality, keywords, indications
- grant_company_relevance: grant_id, company_id, relevance_score, match_reasons

### policies
- bills: id, title, summary, status, relevance_score, passage_likelihood, impact_summary

### portfolio
- companies: id, name, ticker, modality, stage, therapeutic_area
- updates: id, company_name, ticker, title, content, source_type, published_at, impact_score

## PORTFOLIO COMPANIES (for reference)
Key companies include: Montara (mTOR, LRRK2, Parkinson's, tuberous sclerosis), and others in the portfolio_companies tables.

## Your Approach
1. Understand the question - identify which databases are relevant
2. Write targeted SQL queries - you already know the schemas above
3. Analyze results and run follow-up queries as needed
4. Synthesize findings into actionable insights

## Query Guidelines
- Be EFFICIENT - don't explore schemas, use them directly
- Use JOINs to connect related tables
- For "rising stars": use the slope column (h-index growth rate)
- For topic matching: use LIKE on topics column (JSON stored as text)
- Limit large result sets (LIMIT 10-20 for exploration)

## Response Style
- Be analytical and data-driven
- Cite specific numbers and sources
- Use tables for structured data
- Make actionable recommendations

Be DIRECT and EFFICIENT. Skip schema exploration - you have the schemas above."""


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
) -> dict:
    """
    Run the Neo SQL agent to answer a question.

    Args:
        question: The user's question
        model: Claude model to use (default: claude-sonnet-4-20250514)
        max_turns: Maximum tool use iterations (default: 15)
        conversation_history: Optional previous messages for context

    Returns:
        dict with 'answer', 'tool_calls', 'insights', 'model', 'turns_used'
    """
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

            return {
                "answer": final_text,
                "tool_calls": all_tool_calls,
                "insights": insights,
                "model": model,
                "turns_used": turns_used,
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
