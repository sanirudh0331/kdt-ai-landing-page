#!/usr/bin/env python3
"""
Sync clinical trials from ClinicalTrials.gov API to SQLite for Neo querying.

Usage:
    # Sync trials for portfolio companies
    python scripts/sync_clinical_trials.py

    # Sync trials for specific sponsor
    python scripts/sync_clinical_trials.py --sponsor "Pfizer"

    # Sync trials for specific condition
    python scripts/sync_clinical_trials.py --condition "breast cancer"
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional
import httpx

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "clinical_trials.db"

# ClinicalTrials.gov API v2
API_BASE = "https://clinicaltrials.gov/api/v2/studies"

# Portfolio companies to track (add more as needed)
PORTFOLIO_SPONSORS = [
    "Genentech",
    "Roche",
    "Pfizer",
    "Merck",
    "Bristol-Myers Squibb",
    "AbbVie",
    "Novartis",
    "Eli Lilly",
    "Johnson & Johnson",
    "Sanofi",
    "AstraZeneca",
    "Gilead",
    "Amgen",
    "Biogen",
    "Regeneron",
    "Moderna",
    "BioNTech",
    # Add your portfolio companies here
]

# Therapeutic areas of interest
THERAPEUTIC_AREAS = [
    "oncology",
    "immunology",
    "neurology",
    "gene therapy",
    "cell therapy",
    "CRISPR",
]


def create_tables(conn: sqlite3.Connection):
    """Create clinical_trials table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clinical_trials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nct_id TEXT UNIQUE NOT NULL,
            brief_title TEXT,
            official_title TEXT,
            status TEXT,
            phase TEXT,
            study_type TEXT,
            conditions TEXT,  -- JSON array
            interventions TEXT,  -- JSON array
            sponsor TEXT,
            collaborators TEXT,  -- JSON array
            enrollment INTEGER,
            start_date TEXT,
            completion_date TEXT,
            primary_completion_date TEXT,
            study_first_posted TEXT,
            last_update_posted TEXT,
            locations_count INTEGER,
            has_results INTEGER DEFAULT 0,
            url TEXT,
            raw_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Indexes for common queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_status ON clinical_trials(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_phase ON clinical_trials(phase)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_sponsor ON clinical_trials(sponsor)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_start ON clinical_trials(start_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_completion ON clinical_trials(completion_date)")

    conn.commit()
    print("Created clinical_trials table with indexes")


def fetch_trials(
    sponsor: Optional[str] = None,
    condition: Optional[str] = None,
    status: Optional[str] = None,
    page_size: int = 100,
    max_pages: int = 10,
) -> list:
    """Fetch trials from ClinicalTrials.gov API."""

    all_trials = []
    page_token = None

    for page in range(max_pages):
        params = {
            "pageSize": page_size,
            "format": "json",
        }

        # Build query
        query_parts = []
        if sponsor:
            query_parts.append(f"AREA[LeadSponsorName]{sponsor}")
        if condition:
            query_parts.append(f"AREA[Condition]{condition}")
        if status:
            params["filter.overallStatus"] = status

        if query_parts:
            params["query.term"] = " AND ".join(query_parts)

        if page_token:
            params["pageToken"] = page_token

        try:
            response = httpx.get(API_BASE, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            studies = data.get("studies", [])
            all_trials.extend(studies)

            print(f"  Page {page + 1}: fetched {len(studies)} trials")

            # Check for next page
            page_token = data.get("nextPageToken")
            if not page_token:
                break

            # Rate limiting - be nice to the API
            time.sleep(0.5)

        except Exception as e:
            print(f"  Error fetching page {page + 1}: {e}")
            break

    return all_trials


def parse_trial(study: dict) -> dict:
    """Parse a study from the API into a flat dict for the database."""

    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status_module = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    interventions_module = protocol.get("armsInterventionsModule", {})

    # Extract interventions
    interventions = []
    for intervention in interventions_module.get("interventions", []):
        interventions.append({
            "name": intervention.get("name"),
            "type": intervention.get("type"),
        })

    # Extract collaborators
    collaborators = []
    for collab in sponsor_module.get("collaborators", []):
        collaborators.append(collab.get("name"))

    nct_id = identification.get("nctId", "")

    return {
        "nct_id": nct_id,
        "brief_title": identification.get("briefTitle"),
        "official_title": identification.get("officialTitle"),
        "status": status_module.get("overallStatus"),
        "phase": ", ".join(design.get("phases", [])) if design.get("phases") else None,
        "study_type": design.get("studyType"),
        "conditions": json.dumps(conditions_module.get("conditions", [])),
        "interventions": json.dumps(interventions),
        "sponsor": sponsor_module.get("leadSponsor", {}).get("name"),
        "collaborators": json.dumps(collaborators),
        "enrollment": design.get("enrollmentInfo", {}).get("count"),
        "start_date": status_module.get("startDateStruct", {}).get("date"),
        "completion_date": status_module.get("completionDateStruct", {}).get("date"),
        "primary_completion_date": status_module.get("primaryCompletionDateStruct", {}).get("date"),
        "study_first_posted": status_module.get("studyFirstPostDateStruct", {}).get("date"),
        "last_update_posted": status_module.get("lastUpdatePostDateStruct", {}).get("date"),
        "locations_count": len(protocol.get("contactsLocationsModule", {}).get("locations", [])),
        "has_results": 1 if study.get("hasResults") else 0,
        "url": f"https://clinicaltrials.gov/study/{nct_id}",
        "raw_json": json.dumps(study),
    }


def upsert_trial(conn: sqlite3.Connection, trial: dict) -> str:
    """Insert or update a trial. Returns 'inserted', 'updated', or 'skipped'."""

    try:
        conn.execute("""
            INSERT INTO clinical_trials (
                nct_id, brief_title, official_title, status, phase, study_type,
                conditions, interventions, sponsor, collaborators, enrollment,
                start_date, completion_date, primary_completion_date,
                study_first_posted, last_update_posted, locations_count,
                has_results, url, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trial["nct_id"], trial["brief_title"], trial["official_title"],
            trial["status"], trial["phase"], trial["study_type"],
            trial["conditions"], trial["interventions"], trial["sponsor"],
            trial["collaborators"], trial["enrollment"], trial["start_date"],
            trial["completion_date"], trial["primary_completion_date"],
            trial["study_first_posted"], trial["last_update_posted"],
            trial["locations_count"], trial["has_results"], trial["url"],
            trial["raw_json"]
        ))
        return "inserted"
    except sqlite3.IntegrityError:
        # Already exists, update
        conn.execute("""
            UPDATE clinical_trials SET
                brief_title = ?, official_title = ?, status = ?, phase = ?,
                study_type = ?, conditions = ?, interventions = ?, sponsor = ?,
                collaborators = ?, enrollment = ?, start_date = ?,
                completion_date = ?, primary_completion_date = ?,
                study_first_posted = ?, last_update_posted = ?,
                locations_count = ?, has_results = ?, url = ?, raw_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE nct_id = ?
        """, (
            trial["brief_title"], trial["official_title"], trial["status"],
            trial["phase"], trial["study_type"], trial["conditions"],
            trial["interventions"], trial["sponsor"], trial["collaborators"],
            trial["enrollment"], trial["start_date"], trial["completion_date"],
            trial["primary_completion_date"], trial["study_first_posted"],
            trial["last_update_posted"], trial["locations_count"],
            trial["has_results"], trial["url"], trial["raw_json"],
            trial["nct_id"]
        ))
        return "updated"


def main():
    parser = argparse.ArgumentParser(description="Sync clinical trials to SQLite")
    parser.add_argument("--sponsor", help="Sync trials for specific sponsor")
    parser.add_argument("--condition", help="Sync trials for specific condition")
    parser.add_argument("--status", help="Filter by status (e.g., RECRUITING)")
    parser.add_argument("--portfolio", action="store_true", help="Sync for all portfolio companies")
    args = parser.parse_args()

    print("Clinical Trials Sync")
    print("=" * 50)

    # Ensure data directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)

    stats = {"inserted": 0, "updated": 0, "errors": 0}

    if args.sponsor:
        # Single sponsor
        sponsors = [args.sponsor]
    elif args.portfolio:
        # All portfolio companies
        sponsors = PORTFOLIO_SPONSORS
    else:
        # Default: top pharma + biotech
        sponsors = PORTFOLIO_SPONSORS[:5]  # Just first 5 for quick sync

    for sponsor in sponsors:
        print(f"\nFetching trials for: {sponsor}")
        trials = fetch_trials(
            sponsor=sponsor,
            condition=args.condition,
            status=args.status,
            max_pages=5,  # Limit pages per sponsor
        )

        for study in trials:
            try:
                trial = parse_trial(study)
                result = upsert_trial(conn, trial)
                stats[result] += 1
            except Exception as e:
                print(f"  Error parsing trial: {e}")
                stats["errors"] += 1

        conn.commit()
        time.sleep(1)  # Rate limiting between sponsors

    # Final stats
    cursor = conn.execute("SELECT COUNT(*) FROM clinical_trials")
    total = cursor.fetchone()[0]

    cursor = conn.execute("""
        SELECT status, COUNT(*) FROM clinical_trials GROUP BY status ORDER BY COUNT(*) DESC LIMIT 5
    """)
    status_counts = cursor.fetchall()

    print(f"\n" + "=" * 50)
    print(f"Sync complete:")
    print(f"  Inserted: {stats['inserted']}")
    print(f"  Updated: {stats['updated']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Total in DB: {total}")

    print(f"\nTrials by status:")
    for status, count in status_counts:
        print(f"  {status}: {count}")

    # Show sample
    print(f"\nRecent trials:")
    cursor = conn.execute("""
        SELECT nct_id, sponsor, brief_title, status, phase
        FROM clinical_trials
        ORDER BY study_first_posted DESC
        LIMIT 5
    """)
    for row in cursor:
        nct_id, sponsor, title, status, phase = row
        title_short = (title[:50] + "...") if title and len(title) > 50 else title
        print(f"  {nct_id} | {sponsor} | {status} | {phase}")
        print(f"    {title_short}")

    conn.close()
    print(f"\nDatabase saved to: {DB_PATH}")


if __name__ == "__main__":
    main()
