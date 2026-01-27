"""
Fetch databases from Railway services at startup.
Downloads data from existing KdT services and builds local SQLite databases.
"""

import os
import sys
import json
import sqlite3
import httpx
from pathlib import Path
from datetime import datetime

# Data directory
DATA_DIR = Path(__file__).parent.parent / "data"

# Service URLs - same as in ingest.py
SERVICE_URLS = {
    "researchers": os.environ.get("RESEARCHERS_SERVICE_URL", "https://kdttalentscout.up.railway.app"),
    "patents": os.environ.get("PATENT_SERVICE_URL", "https://patentwarrior.up.railway.app"),
    "grants": os.environ.get("GRANTS_SERVICE_URL", "https://grants-tracker-production.up.railway.app"),
    "policies": os.environ.get("POLICY_SERVICE_URL", "https://policywatch.up.railway.app"),
    "portfolio": os.environ.get("PORTFOLIO_SERVICE_URL", "https://web-production-a9d068.up.railway.app"),
}

# Database paths
DB_PATHS = {
    "researchers": DATA_DIR / "researchers.db",
    "patents": DATA_DIR / "patents.db",
    "grants": DATA_DIR / "grants.db",
    "policies": DATA_DIR / "policies.db",
    "portfolio": DATA_DIR / "portfolio.db",
}


def fetch_json(url: str, timeout: int = 120) -> list:
    """Fetch JSON data from a service endpoint."""
    try:
        print(f"  Fetching from {url}...")
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("data", data) if isinstance(data, dict) else data
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return []


def create_researchers_db(data: list, db_path: Path):
    """Create researchers database from API data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS researchers (
            id TEXT PRIMARY KEY,
            name TEXT,
            orcid TEXT,
            h_index INTEGER,
            i10_index INTEGER,
            works_count INTEGER,
            cited_by_count INTEGER,
            two_yr_citedness REAL,
            topics TEXT,
            affiliations TEXT,
            counts_by_year TEXT,
            slope REAL,
            primary_category TEXT,
            synced_from TEXT,
            also_found_in TEXT,
            institution_count INTEGER,
            likely_bad_merge INTEGER DEFAULT 0,
            alternative_names TEXT,
            twitter TEXT,
            wikipedia TEXT,
            computed_primary TEXT,
            primary_computed INTEGER DEFAULT 0,
            affiliation_scores TEXT,
            kdt_team_member TEXT,
            kdt_connection_date TEXT,
            kdt_connection_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            history_computed INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS h_index_history (
            researcher_id TEXT,
            year INTEGER,
            h_index INTEGER,
            PRIMARY KEY (researcher_id, year)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topic_categories (
            topic_name TEXT PRIMARY KEY,
            category TEXT
        )
    """)

    # Insert data
    for r in data:
        cursor.execute("""
            INSERT OR REPLACE INTO researchers
            (id, name, orcid, h_index, i10_index, works_count, cited_by_count,
             two_yr_citedness, topics, affiliations, counts_by_year, slope,
             primary_category, likely_bad_merge)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r.get("id"),
            r.get("name"),
            r.get("orcid"),
            r.get("h_index"),
            r.get("i10_index"),
            r.get("works_count"),
            r.get("cited_by_count"),
            r.get("two_yr_citedness"),
            json.dumps(r.get("topics")) if r.get("topics") else None,
            json.dumps(r.get("affiliations")) if r.get("affiliations") else None,
            json.dumps(r.get("counts_by_year")) if r.get("counts_by_year") else None,
            r.get("slope"),
            r.get("primary_category") or r.get("category"),
            r.get("likely_bad_merge", 0)
        ))

        # Insert h_index history if available
        if r.get("h_index_history"):
            for year, h_idx in r["h_index_history"].items():
                cursor.execute("""
                    INSERT OR REPLACE INTO h_index_history (researcher_id, year, h_index)
                    VALUES (?, ?, ?)
                """, (r.get("id"), int(year), h_idx))

    conn.commit()
    conn.close()
    print(f"  Created researchers.db with {len(data)} researchers")


def create_patents_db(data: list, db_path: Path):
    """Create patents database from API data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patents (
            id TEXT PRIMARY KEY,
            patent_number TEXT,
            title TEXT,
            abstract TEXT,
            grant_date TEXT,
            filing_date TEXT,
            application_number TEXT,
            patent_type TEXT,
            assignee_type TEXT,
            primary_assignee TEXT,
            cpc_codes TEXT,
            us_classes TEXT,
            claims_count INTEGER,
            claims_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patent_id TEXT,
            name TEXT,
            sequence INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cpc_classifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patent_id TEXT,
            section TEXT,
            class_code TEXT,
            subclass TEXT,
            group_code TEXT,
            subgroup TEXT,
            full_code TEXT,
            is_primary INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_companies (
            id TEXT PRIMARY KEY,
            name TEXT,
            modality TEXT,
            competitive_advantage TEXT,
            keywords TEXT,
            indications TEXT,
            fund INTEGER,
            cpc_codes TEXT,
            watch_inventors TEXT,
            watch_assignees TEXT,
            ai_context TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patent_company_relevance (
            patent_id TEXT,
            company_id TEXT,
            relevance_score REAL,
            match_reasons TEXT,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            inventor_alert TEXT,
            assignee_alert TEXT,
            PRIMARY KEY (patent_id, company_id)
        )
    """)

    # Insert patents
    for p in data:
        cursor.execute("""
            INSERT OR REPLACE INTO patents
            (id, patent_number, title, abstract, grant_date, filing_date,
             application_number, patent_type, primary_assignee, cpc_codes, claims_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            p.get("id"),
            p.get("patent_number"),
            p.get("title"),
            p.get("abstract"),
            p.get("grant_date"),
            p.get("filing_date"),
            p.get("application_number"),
            p.get("patent_type"),
            p.get("primary_assignee"),
            p.get("cpc_codes"),
            p.get("claims_count")
        ))

        # Insert inventors
        for i, inv in enumerate(p.get("inventors", [])):
            inv_name = inv.get("name") if isinstance(inv, dict) else inv
            cursor.execute("""
                INSERT INTO inventors (patent_id, name, sequence)
                VALUES (?, ?, ?)
            """, (p.get("id"), inv_name, i))

    conn.commit()
    conn.close()
    print(f"  Created patents.db with {len(data)} patents")


def create_grants_db(data: list, db_path: Path):
    """Create grants database from API data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grants (
            id TEXT PRIMARY KEY,
            project_number TEXT,
            title TEXT,
            abstract TEXT,
            agency TEXT,
            mechanism TEXT,
            total_cost REAL,
            award_notice_date TEXT,
            project_start_date TEXT,
            project_end_date TEXT,
            organization_name TEXT,
            pi_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS principal_investigators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grant_id TEXT,
            name TEXT,
            title TEXT,
            organization TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_companies (
            id TEXT PRIMARY KEY,
            name TEXT,
            modality TEXT,
            keywords TEXT,
            indications TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grant_company_relevance (
            grant_id TEXT,
            company_id TEXT,
            relevance_score REAL,
            match_reasons TEXT,
            PRIMARY KEY (grant_id, company_id)
        )
    """)

    # Insert grants
    for g in data:
        cursor.execute("""
            INSERT OR REPLACE INTO grants
            (id, project_number, title, abstract, agency, mechanism,
             total_cost, award_notice_date, project_start_date, project_end_date,
             organization_name, pi_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            g.get("id"),
            g.get("project_number"),
            g.get("title"),
            g.get("abstract"),
            g.get("agency"),
            g.get("mechanism"),
            g.get("total_cost"),
            g.get("award_notice_date"),
            g.get("project_start_date"),
            g.get("project_end_date"),
            g.get("organization_name"),
            g.get("pi_name") or g.get("pi_names")
        ))

    conn.commit()
    conn.close()
    print(f"  Created grants.db with {len(data)} grants")


def create_policies_db(data: list, db_path: Path):
    """Create policies database from API data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables based on what PolicyWatch likely has
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bills (
            id TEXT PRIMARY KEY,
            title TEXT,
            summary TEXT,
            status TEXT,
            relevance_score REAL,
            passage_likelihood TEXT,
            impact_summary TEXT,
            source_url TEXT,
            published_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id TEXT,
            analysis_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)

    # Insert policies/bills
    for p in data:
        cursor.execute("""
            INSERT OR REPLACE INTO bills
            (id, title, summary, status, relevance_score, passage_likelihood, impact_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            p.get("id"),
            p.get("title"),
            p.get("summary"),
            p.get("status"),
            p.get("relevance_score"),
            p.get("passage_likelihood"),
            p.get("impact_summary")
        ))

    conn.commit()
    conn.close()
    print(f"  Created policies.db with {len(data)} policies")


def create_portfolio_db(data: list, db_path: Path):
    """Create portfolio database from API data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY,
            name TEXT,
            ticker TEXT,
            modality TEXT,
            stage TEXT,
            therapeutic_area TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS updates (
            id TEXT PRIMARY KEY,
            company_name TEXT,
            ticker TEXT,
            title TEXT,
            content TEXT,
            source_type TEXT,
            source_url TEXT,
            published_at TEXT,
            impact_score REAL,
            position_status TEXT
        )
    """)

    # Insert data
    for item in data:
        # Could be a company or an update depending on API structure
        if item.get("content") or item.get("title"):
            cursor.execute("""
                INSERT OR REPLACE INTO updates
                (id, company_name, ticker, title, content, source_type,
                 source_url, published_at, impact_score, position_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.get("id"),
                item.get("company_name"),
                item.get("ticker"),
                item.get("title"),
                item.get("content"),
                item.get("source_type"),
                item.get("source_url"),
                item.get("published_at"),
                item.get("impact_score"),
                item.get("position_status")
            ))

    conn.commit()
    conn.close()
    print(f"  Created portfolio.db with {len(data)} items")


def fetch_all_databases(force: bool = False):
    """Fetch all databases from Railway services."""
    print(f"\n{'='*50}")
    print("Neo Database Sync")
    print(f"{'='*50}\n")

    # Create data directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Check if we should skip (databases exist and not forcing)
    all_exist = all(db.exists() for db in DB_PATHS.values())
    if all_exist and not force:
        # Check age - refresh if older than 24 hours
        oldest = min(db.stat().st_mtime for db in DB_PATHS.values())
        age_hours = (datetime.now().timestamp() - oldest) / 3600
        if age_hours < 24:
            print(f"Databases exist and are {age_hours:.1f} hours old. Skipping sync.")
            print("Use --force to refresh anyway.\n")
            return True
        print(f"Databases are {age_hours:.1f} hours old. Refreshing...")

    success = True

    # Fetch researchers
    print("\n[1/5] Researchers...")
    data = fetch_json(f"{SERVICE_URLS['researchers']}/api/export")
    if data:
        create_researchers_db(data, DB_PATHS["researchers"])
    else:
        print("  Warning: No researcher data fetched")
        success = False

    # Fetch patents
    print("\n[2/5] Patents...")
    data = fetch_json(f"{SERVICE_URLS['patents']}/api/export")
    if data:
        create_patents_db(data, DB_PATHS["patents"])
    else:
        print("  Warning: No patent data fetched")
        success = False

    # Fetch grants
    print("\n[3/5] Grants...")
    data = fetch_json(f"{SERVICE_URLS['grants']}/api/export")
    if data:
        create_grants_db(data, DB_PATHS["grants"])
    else:
        print("  Warning: No grant data fetched")
        success = False

    # Fetch policies
    print("\n[4/5] Policies...")
    data = fetch_json(f"{SERVICE_URLS['policies']}/api/export")
    if data:
        create_policies_db(data, DB_PATHS["policies"])
    else:
        print("  Warning: No policy data fetched")
        success = False

    # Fetch portfolio
    print("\n[5/5] Portfolio...")
    data = fetch_json(f"{SERVICE_URLS['portfolio']}/api/export")
    if data:
        create_portfolio_db(data, DB_PATHS["portfolio"])
    else:
        print("  Warning: No portfolio data fetched")
        success = False

    print(f"\n{'='*50}")
    if success:
        print("Database sync complete!")
    else:
        print("Database sync completed with warnings")
    print(f"{'='*50}\n")

    return success


if __name__ == "__main__":
    force = "--force" in sys.argv
    fetch_all_databases(force=force)
