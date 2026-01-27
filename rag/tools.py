"""
Tool definitions for Neo SQL agent.
These replicate the MCP tools for direct database access.
"""

from typing import Callable

# Tool definitions for Claude's tool_use API
TOOLS = [
    {
        "name": "query_researchers",
        "description": """Execute a SQL SELECT query against the researchers database.

Contains data on scientific researchers including:
- researchers: id, name, h_index, i10_index, works_count, cited_by_count, two_yr_citedness, topics (JSON), affiliations (JSON), slope (h-index growth rate), primary_category
- h_index_history: researcher_id, year, h_index (historical h-index by year)
- topic_categories: topic_name, category

Use this for finding researchers by expertise, tracking rising stars (high slope), analyzing research trends, and identifying talent for specific therapeutic areas.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query to execute"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "query_patents",
        "description": """Execute a SQL SELECT query against the patents database.

Contains patent data including:
- patents: id, patent_number, title, abstract, grant_date, filing_date, application_number, patent_type, assignee_type, primary_assignee, cpc_codes, claims_count
- inventors: patent_id, name, sequence
- assignees: patent_id, name, type
- cpc_classifications: patent_id, section, class_code, subclass, group_code, full_code, is_primary
- portfolio_companies: id, name, modality, competitive_advantage, keywords, indications, cpc_codes
- patent_company_relevance: patent_id, company_id, relevance_score, match_reasons
- patent_summaries: patent_id, summary, key_claims

Use this for patent landscape analysis, competitive intelligence, finding patents relevant to portfolio companies, and tracking technology trends.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query to execute"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "query_grants",
        "description": """Execute a SQL SELECT query against the grants database.

Contains NIH/SBIR grant data including:
- grants: id, project_number, title, abstract, agency, mechanism, total_cost, award_notice_date, project_start_date, project_end_date, organization_name, pi_name
- grant_summaries: grant_id, summary, relevance_notes
- principal_investigators: grant_id, name, title, organization
- portfolio_companies: id, name, modality, keywords, indications
- grant_company_relevance: grant_id, company_id, relevance_score, match_reasons

Use this for tracking research funding, finding grants relevant to therapeutic areas, identifying funded researchers, and competitive intelligence.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query to execute"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "query_policies",
        "description": """Execute a SQL SELECT query against the policies database.

Contains policy/regulatory tracking data including:
- policies: id, title, summary, status, relevance_score, passage_likelihood, impact_summary, source_url, published_date
- policy_tags: policy_id, tag
- policy_updates: policy_id, update_date, update_text

Use this for tracking regulatory changes, legislation that may impact biotech, and policy developments relevant to the portfolio.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query to execute"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "query_portfolio",
        "description": """Execute a SQL SELECT query against the portfolio database.

Contains portfolio company updates and news including:
- updates: id, company_name, ticker, title, content, source_type, source_url, published_at, impact_score, position_status
- companies: id, name, ticker, modality, stage, therapeutic_area

Use this for tracking portfolio company news, competitive updates, and market developments.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query to execute"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_tables",
        "description": """List all tables in a specified database.

Available databases: researchers, patents, grants, policies, portfolio

Use this to discover what tables are available before writing queries.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "enum": ["researchers", "patents", "grants", "policies", "portfolio"],
                    "description": "Which database to list tables from"
                }
            },
            "required": ["database"]
        }
    },
    {
        "name": "describe_table",
        "description": """Get the schema (columns, types) for a specific table.

Use this to understand table structure before writing queries.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "enum": ["researchers", "patents", "grants", "policies", "portfolio"],
                    "description": "Which database the table is in"
                },
                "table_name": {
                    "type": "string",
                    "description": "Name of the table to describe"
                }
            },
            "required": ["database", "table_name"]
        }
    },
    {
        "name": "append_insight",
        "description": """Record a business insight discovered during analysis.

Use this to capture key findings, recommendations, or observations that should be highlighted in the final response.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "insight": {
                    "type": "string",
                    "description": "The business insight to record"
                }
            },
            "required": ["insight"]
        }
    }
]


def get_tool_names() -> list[str]:
    """Get list of all tool names."""
    return [tool["name"] for tool in TOOLS]


def get_tool_by_name(name: str) -> dict:
    """Get a tool definition by name."""
    for tool in TOOLS:
        if tool["name"] == name:
            return tool
    return None
