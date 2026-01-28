"""
Tool definitions for Neo SQL agent.
Includes both raw SQL tools and semantic functions for structured access.

Semantic functions provide:
- Pre-validated queries with proper joins and filters
- Business context and insights
- Cross-database entity resolution
- Optimized performance with caching
"""

from typing import Callable

# Tool definitions for Claude's tool_use API
TOOLS = [
    # =============================================================================
    # SEMANTIC FUNCTIONS - Preferred for common queries (faster, more accurate)
    # =============================================================================

    # --- RESEARCHERS SEMANTIC FUNCTIONS ---
    {
        "name": "get_researchers",
        "description": """Find researchers with optional filters. Returns top researchers matching criteria.

Use this instead of raw SQL for researcher lookups. Handles JSON topic parsing automatically.

Returns: id, name, h_index, slope, affiliations, topics, primary_category""",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_h_index": {
                    "type": "integer",
                    "description": "Minimum h-index (default: no minimum)"
                },
                "topic": {
                    "type": "string",
                    "description": "Research topic to search for (searches topics JSON field)"
                },
                "affiliation": {
                    "type": "string",
                    "description": "Institution/affiliation to filter by"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_researcher_profile",
        "description": """Get detailed profile for a specific researcher by name.

Returns full profile including h-index history, topics, affiliations, and publication metrics.
Includes trajectory analysis (rising star vs established vs declining).""",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Researcher name (partial match supported)"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "get_rising_stars",
        "description": """Find researchers with fast-growing h-index (rising stars).

These are researchers whose h-index is growing faster than peers - potential talent for hiring or collaboration.
Slope > 3 indicates very fast growth.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_slope": {
                    "type": "number",
                    "description": "Minimum h-index growth rate (default: 2.0)"
                },
                "min_h_index": {
                    "type": "integer",
                    "description": "Minimum current h-index (default: 15)"
                },
                "max_h_index": {
                    "type": "integer",
                    "description": "Maximum h-index to exclude established researchers (default: 80)"
                },
                "topic": {
                    "type": "string",
                    "description": "Filter by research topic"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_researchers_by_topic",
        "description": """Find top researchers in a specific research area.

Returns researchers ranked by h-index who work in the specified topic area.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Research topic (e.g., 'CRISPR', 'mRNA', 'immunotherapy', 'gene therapy')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            },
            "required": ["topic"]
        }
    },

    # --- PATENTS SEMANTIC FUNCTIONS ---
    {
        "name": "get_patents",
        "description": """Search patents with filters. Returns matching patents with key metadata.

Use this instead of raw SQL for patent lookups.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "assignee": {
                    "type": "string",
                    "description": "Company/organization that owns the patent"
                },
                "inventor": {
                    "type": "string",
                    "description": "Inventor name"
                },
                "cpc_code": {
                    "type": "string",
                    "description": "CPC classification code (e.g., 'A61K' for pharma, 'C12N' for biotech)"
                },
                "days": {
                    "type": "integer",
                    "description": "Only patents granted in last N days"
                },
                "keyword": {
                    "type": "string",
                    "description": "Search in title and abstract"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_patent_portfolio",
        "description": """Get complete patent portfolio for a company/assignee.

Returns summary statistics and list of patents owned by the assignee.
Includes: total patents, filing trends, top CPC codes, recent filings.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "assignee": {
                    "type": "string",
                    "description": "Company/organization name"
                }
            },
            "required": ["assignee"]
        }
    },
    {
        "name": "get_inventors_by_company",
        "description": """Get top inventors at a company based on patent count.

Returns inventors who have filed patents assigned to the specified company.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "assignee": {
                    "type": "string",
                    "description": "Company/organization name"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            },
            "required": ["assignee"]
        }
    },
    {
        "name": "search_patents_by_topic",
        "description": """Search patents by technology topic using keywords.

Searches title and abstract for relevant patents. Good for landscape analysis.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "Keywords to search (e.g., 'mRNA delivery', 'CAR-T', 'gene editing')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            },
            "required": ["keywords"]
        }
    },

    # --- GRANTS SEMANTIC FUNCTIONS ---
    {
        "name": "get_grants",
        "description": """Search grants with filters. Returns matching grants with funding details.

Use this instead of raw SQL for grant lookups.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "organization": {
                    "type": "string",
                    "description": "Institution receiving the grant"
                },
                "pi_name": {
                    "type": "string",
                    "description": "Principal investigator name"
                },
                "mechanism": {
                    "type": "string",
                    "description": "Grant type: R01, R21, SBIR, STTR, K, U, etc."
                },
                "min_amount": {
                    "type": "integer",
                    "description": "Minimum total funding amount"
                },
                "institute": {
                    "type": "string",
                    "description": "NIH institute (e.g., 'NCI', 'NIAID', 'NIGMS')"
                },
                "keyword": {
                    "type": "string",
                    "description": "Search in title and abstract"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_funding_summary",
        "description": """Get funding summary for an organization.

Returns total funding, grant count by mechanism, top-funded projects, and recent awards.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "organization": {
                    "type": "string",
                    "description": "Institution name"
                }
            },
            "required": ["organization"]
        }
    },
    {
        "name": "get_pis_by_organization",
        "description": """Get principal investigators at an organization ranked by funding.

Returns PIs with their total funding, grant count, and top projects.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "organization": {
                    "type": "string",
                    "description": "Institution name"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            },
            "required": ["organization"]
        }
    },
    {
        "name": "get_grants_by_topic",
        "description": """Search grants by research topic using keywords.

Searches title and abstract for relevant grants. Good for funding landscape analysis.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "Keywords to search (e.g., 'CRISPR', 'mRNA vaccine', 'CAR-T therapy')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            },
            "required": ["keywords"]
        }
    },

    # --- CROSS-DATABASE FUNCTIONS ---
    {
        "name": "search_entity",
        "description": """Search for an entity (company, university, person) across all databases.

Finds the entity and shows what data exists about it in each database (patents, grants, researchers).
Uses the entity_links table to resolve name variations.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Entity name to search for"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "get_company_profile",
        "description": """Get unified profile of a company from all databases.

Aggregates: patents owned, grants received, researchers affiliated, SEC filings (if available).
Provides a 360-degree view of the company's research and IP footprint.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Company name"
                }
            },
            "required": ["name"]
        }
    },

    # --- SEC SENTINEL SEMANTIC FUNCTIONS ---
    {
        "name": "get_sec_filings",
        "description": """Search SEC filings (8-K, 10-K, 10-Q, S-1, S-3, Form 4) with optional runway status.

Returns filings with linked runway data. Can filter by runway status to find filings from distressed companies.
Form types: 8-K (material events), 10-K (annual), 10-Q (quarterly), S-1 (IPO), S-3 (shelf/fundraising), 4 (insider), SC 13D/G (ownership).""",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol"
                },
                "form_type": {
                    "type": "string",
                    "description": "Filing type: 8-K, 10-K, 10-Q, S-1, S-3, 4, SC 13D"
                },
                "days": {
                    "type": "integer",
                    "description": "Look back N days (default: 30)"
                },
                "runway_status": {
                    "type": "string",
                    "enum": ["critical", "low", "moderate", "healthy"],
                    "description": "Filter by runway status: critical (<6mo), low (6-12mo), moderate (12-24mo), healthy (>24mo)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_companies_by_runway",
        "description": """Find companies by cash runway status.

Returns companies sorted by runway (lowest first). Critical runway (<6 months) often precedes fundraising or acquisition.
Includes runway status classification: critical, low, moderate, healthy.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_months": {
                    "type": "number",
                    "description": "Maximum runway in months (e.g., 6 for critical only)"
                },
                "min_months": {
                    "type": "number",
                    "description": "Minimum runway in months (default: 0)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 50)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_insider_transactions",
        "description": """Search insider trading transactions (Form 4 data).

Returns insider buys and sells with linked runway data. Insider buys at distressed companies can be bullish; sells at low-runway companies are bearish.
Flags transactions at companies with low runway automatically.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol"
                },
                "insider_role": {
                    "type": "string",
                    "description": "Filter by role: CEO, CFO, Director, etc."
                },
                "transaction_type": {
                    "type": "string",
                    "enum": ["buy", "sell"],
                    "description": "Filter by buy or sell"
                },
                "days": {
                    "type": "integer",
                    "description": "Look back N days (default: 90)"
                },
                "min_value": {
                    "type": "number",
                    "description": "Minimum transaction value in dollars"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_runway_alerts",
        "description": """Get distress signal alerts: companies with critical runway, recent S-3 filings (fundraising), and insider sells at risk companies.

This is the key watchlist function - combines runway, filings, and insider data to identify highest-risk situations.
Pattern: critical runway + S-3 filing + insider sells = maximum distress signal.""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },

    # =============================================================================
    # RAW SQL TOOLS - Use when semantic functions don't cover the query
    # =============================================================================
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
        "name": "query_market_data",
        "description": """Execute a SQL SELECT query against the market_data database.

Contains clinical trials and FDA calendar data (89,000+ trials):
- clinical_trials: id, nct_id, brief_title, official_title, status, phase, study_type, conditions (JSON), interventions (JSON), sponsor, collaborators (JSON), enrollment, start_date, completion_date, primary_completion_date, study_first_posted, last_update_posted, locations_count, has_results, url
- fda_events: id, event_type, ticker, company, drug, indication, event_date, url

Status values: RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, NOT_YET_RECRUITING, TERMINATED, WITHDRAWN, SUSPENDED, ENROLLING_BY_INVITATION
Phase values: PHASE1, PHASE2, PHASE3, PHASE4, EARLY_PHASE1, NA (or NULL)

Use this for clinical trial landscape analysis, tracking company pipelines, finding trials by condition/phase/sponsor, and FDA calendar events.""",
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

Available databases: researchers, patents, grants, policies, portfolio, market_data

Use this to discover what tables are available before writing queries.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "enum": ["researchers", "patents", "grants", "policies", "portfolio", "market_data"],
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
                    "enum": ["researchers", "patents", "grants", "policies", "portfolio", "market_data"],
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
