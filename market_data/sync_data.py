#!/usr/bin/env python3
"""
Sync FDA calendar and clinical trials data to SQLite databases.
Run this on the Railway service to populate the volume.

Usage:
    python sync_data.py                     # Sync everything
    python sync_data.py --fda-only          # Just FDA calendar
    python sync_data.py --trials-only       # Just clinical trials
    python sync_data.py --sponsor "Pfizer"  # Trials for specific sponsor
"""

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import httpx

# Paths
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
FDA_DB_PATH = DATA_DIR / "fda_calendar.db"
TRIALS_DB_PATH = DATA_DIR / "clinical_trials.db"

# ClinicalTrials.gov API v2
TRIALS_API_BASE = "https://clinicaltrials.gov/api/v2/studies"

# FDA Calendar source (your static JSON)
FDA_CALENDAR_URL = os.environ.get(
    "FDA_CALENDAR_URL",
    "https://kdt-ai-landing-page-production.up.railway.app/static/fda-calendar.json"
)

# Portfolio companies to track
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
]

# Active trial statuses (for Option C: all active + recent completed)
ACTIVE_STATUSES = [
    "RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "NOT_YET_RECRUITING",
    "ENROLLING_BY_INVITATION",
]

COMPLETED_STATUSES = [
    "COMPLETED",
    "TERMINATED",
    "WITHDRAWN",
    "SUSPENDED",
]


# ============ FDA Calendar ============

def create_fda_table(conn: sqlite3.Connection):
    """Create fda_events table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fda_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            ticker TEXT,
            company TEXT NOT NULL,
            drug TEXT,
            indication TEXT,
            event_date TEXT NOT NULL,
            url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, drug, event_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fda_date ON fda_events(event_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fda_company ON fda_events(company)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fda_ticker ON fda_events(ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fda_type ON fda_events(event_type)")
    conn.commit()


def sync_fda_calendar():
    """Sync FDA calendar from JSON source."""
    print("\n=== Syncing FDA Calendar ===")

    # Fetch JSON
    print(f"Fetching from: {FDA_CALENDAR_URL}")
    try:
        response = httpx.get(FDA_CALENDAR_URL, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Error fetching FDA calendar: {e}")
        return

    events = data.get("events", [])
    print(f"Found {len(events)} events")

    # Ensure directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Sync to database
    conn = sqlite3.connect(FDA_DB_PATH)
    create_fda_table(conn)

    stats = {"inserted": 0, "updated": 0}

    for event in events:
        company = event.get("company", "").rstrip("\\").strip()
        drug = event.get("drug", "").strip() or None
        indication = event.get("indication", "").strip() or None

        try:
            conn.execute("""
                INSERT INTO fda_events (event_type, ticker, company, drug, indication, event_date, url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                event.get("type", "PDUFA"),
                event.get("ticker"),
                company,
                drug,
                indication,
                event.get("date"),
                event.get("url")
            ))
            stats["inserted"] += 1
        except sqlite3.IntegrityError:
            conn.execute("""
                UPDATE fda_events
                SET event_type = ?, ticker = ?, indication = ?, url = ?, updated_at = CURRENT_TIMESTAMP
                WHERE company = ? AND drug = ? AND event_date = ?
            """, (
                event.get("type", "PDUFA"),
                event.get("ticker"),
                indication,
                event.get("url"),
                company,
                drug,
                event.get("date")
            ))
            stats["updated"] += 1

    conn.commit()

    # Get final count
    cursor = conn.execute("SELECT COUNT(*) FROM fda_events")
    total = cursor.fetchone()[0]
    conn.close()

    print(f"Inserted: {stats['inserted']}, Updated: {stats['updated']}, Total: {total}")
    print(f"Database: {FDA_DB_PATH}")


# ============ Clinical Trials ============

def create_trials_table(conn: sqlite3.Connection):
    """Create clinical_trials table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clinical_trials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nct_id TEXT UNIQUE NOT NULL,
            brief_title TEXT,
            official_title TEXT,
            status TEXT,
            phase TEXT,
            study_type TEXT,
            conditions TEXT,
            interventions TEXT,
            sponsor TEXT,
            collaborators TEXT,
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_status ON clinical_trials(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_phase ON clinical_trials(phase)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_sponsor ON clinical_trials(sponsor)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_start ON clinical_trials(start_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_completion ON clinical_trials(completion_date)")
    conn.commit()


def fetch_trials(
    sponsor: Optional[str] = None,
    condition: Optional[str] = None,
    status: Optional[str] = None,
    statuses: Optional[list] = None,
    min_date: Optional[str] = None,
    page_size: int = 100,
    max_pages: int = 10,
) -> list:
    """Fetch trials from ClinicalTrials.gov API.

    Args:
        sponsor: Filter by lead sponsor name
        condition: Filter by condition/disease
        status: Single status filter (deprecated, use statuses)
        statuses: List of statuses to filter by
        min_date: Minimum study first posted date (YYYY-MM-DD)
        page_size: Results per page
        max_pages: Maximum pages to fetch
    """
    all_trials = []
    page_token = None

    for page in range(max_pages):
        params = {
            "pageSize": page_size,
            "format": "json",
        }

        query_parts = []
        if sponsor:
            query_parts.append(f"AREA[LeadSponsorName]{sponsor}")
        if condition:
            query_parts.append(f"AREA[Condition]{condition}")
        if min_date:
            query_parts.append(f"AREA[StudyFirstPostDate]RANGE[{min_date},MAX]")

        # Handle status filtering
        if statuses:
            params["filter.overallStatus"] = ",".join(statuses)
        elif status:
            params["filter.overallStatus"] = status

        if query_parts:
            params["query.term"] = " AND ".join(query_parts)

        if page_token:
            params["pageToken"] = page_token

        try:
            response = httpx.get(TRIALS_API_BASE, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            studies = data.get("studies", [])
            all_trials.extend(studies)
            print(f"  Page {page + 1}: fetched {len(studies)} trials")

            page_token = data.get("nextPageToken")
            if not page_token:
                break

            time.sleep(0.5)  # Rate limiting

        except Exception as e:
            print(f"  Error fetching page {page + 1}: {e}")
            break

    return all_trials


def parse_trial(study: dict) -> dict:
    """Parse a study from the API into a flat dict."""
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status_module = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    interventions_module = protocol.get("armsInterventionsModule", {})

    interventions = []
    for intervention in interventions_module.get("interventions", []):
        interventions.append({
            "name": intervention.get("name"),
            "type": intervention.get("type"),
        })

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
    """Insert or update a trial."""
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


def sync_clinical_trials(
    sponsor: Optional[str] = None,
    max_sponsors: int = 17,
    active_only: bool = False,
    completed_since: str = "2023-01-01",
):
    """Sync clinical trials data using Option C: all active + recent completed.

    Args:
        sponsor: Sync only this sponsor (optional)
        max_sponsors: Max sponsors to sync (default: all 17)
        active_only: Only sync active trials (skip completed)
        completed_since: Date cutoff for completed trials (default: 2023-01-01)
    """
    print("\n=== Syncing Clinical Trials ===")
    print(f"Strategy: All active trials + completed since {completed_since}")

    # Ensure directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(TRIALS_DB_PATH)
    create_trials_table(conn)

    stats = {"inserted": 0, "updated": 0, "errors": 0}

    if sponsor:
        sponsors = [sponsor]
    else:
        sponsors = PORTFOLIO_SPONSORS[:max_sponsors]

    for sponsor_name in sponsors:
        # Part 1: Fetch ALL active trials (any date)
        print(f"\n[{sponsor_name}] Fetching active trials...")
        active_trials = fetch_trials(
            sponsor=sponsor_name,
            statuses=ACTIVE_STATUSES,
            max_pages=10,  # More pages for active trials
        )
        print(f"  Found {len(active_trials)} active trials")

        for study in active_trials:
            try:
                trial = parse_trial(study)
                result = upsert_trial(conn, trial)
                stats[result] += 1
            except Exception as e:
                print(f"  Error parsing trial: {e}")
                stats["errors"] += 1

        conn.commit()

        # Part 2: Fetch completed trials since cutoff date
        if not active_only:
            print(f"[{sponsor_name}] Fetching completed trials since {completed_since}...")
            completed_trials = fetch_trials(
                sponsor=sponsor_name,
                statuses=COMPLETED_STATUSES,
                min_date=completed_since,
                max_pages=5,
            )
            print(f"  Found {len(completed_trials)} completed trials")

            for study in completed_trials:
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
        SELECT status, COUNT(*) as cnt FROM clinical_trials
        GROUP BY status ORDER BY cnt DESC
    """)
    status_breakdown = cursor.fetchall()

    conn.close()

    print(f"\n{'='*50}")
    print(f"Sync complete!")
    print(f"  Inserted: {stats['inserted']}")
    print(f"  Updated: {stats['updated']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Total in DB: {total}")
    print(f"\nBy status:")
    for status, cnt in status_breakdown:
        print(f"  {status}: {cnt}")
    print(f"\nDatabase: {TRIALS_DB_PATH}")


# ============ Main ============

def main():
    parser = argparse.ArgumentParser(description="Sync market data to SQLite")
    parser.add_argument("--fda-only", action="store_true", help="Only sync FDA calendar")
    parser.add_argument("--trials-only", action="store_true", help="Only sync clinical trials")
    parser.add_argument("--sponsor", help="Sync trials for specific sponsor")
    parser.add_argument("--max-sponsors", type=int, default=17, help="Max sponsors to sync (default: all 17)")
    parser.add_argument("--active-only", action="store_true", help="Only sync active trials (skip completed)")
    parser.add_argument("--completed-since", default="2023-01-01", help="Date cutoff for completed trials (default: 2023-01-01)")
    args = parser.parse_args()

    print("KdT Market Data Sync")
    print("=" * 50)
    print(f"Data directory: {DATA_DIR}")

    if args.fda_only:
        sync_fda_calendar()
    elif args.trials_only:
        sync_clinical_trials(
            sponsor=args.sponsor,
            max_sponsors=args.max_sponsors,
            active_only=args.active_only,
            completed_since=args.completed_since,
        )
    else:
        sync_fda_calendar()
        sync_clinical_trials(
            sponsor=args.sponsor,
            max_sponsors=args.max_sponsors,
            active_only=args.active_only,
            completed_since=args.completed_since,
        )

    print("\n" + "=" * 50)
    print("Sync complete!")


if __name__ == "__main__":
    main()
