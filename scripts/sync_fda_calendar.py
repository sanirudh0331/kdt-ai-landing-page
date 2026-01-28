#!/usr/bin/env python3
"""
Sync FDA calendar JSON to SQLite for Neo querying.
Run this whenever fda-calendar.json is updated.

Usage:
    python scripts/sync_fda_calendar.py
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
FDA_JSON_PATH = PROJECT_DIR / "static" / "fda-calendar.json"
DB_PATH = PROJECT_DIR / "data" / "fda_calendar.db"


def create_table(conn: sqlite3.Connection):
    """Create fda_events table if it doesn't exist."""
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

    # Create indexes for common queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fda_date ON fda_events(event_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fda_company ON fda_events(company)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fda_ticker ON fda_events(ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fda_type ON fda_events(event_type)")

    conn.commit()
    print("Created fda_events table with indexes")


def sync_events(conn: sqlite3.Connection, events: list) -> dict:
    """Sync events from JSON to database."""
    stats = {"inserted": 0, "updated": 0, "skipped": 0}

    for event in events:
        # Clean up company names (remove trailing backslashes)
        company = event.get("company", "").rstrip("\\").strip()
        drug = event.get("drug", "").strip() or None
        indication = event.get("indication", "").strip() or None

        try:
            # Try to insert
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
            # Already exists, update it
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
    return stats


def main():
    print(f"FDA Calendar Sync")
    print(f"=" * 50)

    # Load JSON
    if not FDA_JSON_PATH.exists():
        print(f"Error: {FDA_JSON_PATH} not found")
        return

    with open(FDA_JSON_PATH) as f:
        data = json.load(f)

    events = data.get("events", [])
    last_updated = data.get("lastUpdated", "unknown")
    print(f"Source: {FDA_JSON_PATH}")
    print(f"Last updated: {last_updated}")
    print(f"Events in JSON: {len(events)}")

    # Ensure data directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Connect to database
    conn = sqlite3.connect(DB_PATH)

    # Create table
    create_table(conn)

    # Sync events
    stats = sync_events(conn, events)

    # Get final count
    cursor = conn.execute("SELECT COUNT(*) FROM fda_events")
    total = cursor.fetchone()[0]

    print(f"\nSync complete:")
    print(f"  Inserted: {stats['inserted']}")
    print(f"  Updated: {stats['updated']}")
    print(f"  Total in DB: {total}")

    # Show upcoming events
    print(f"\nUpcoming PDUFA dates:")
    cursor = conn.execute("""
        SELECT event_date, company, drug, indication
        FROM fda_events
        WHERE event_date >= date('now')
        ORDER BY event_date
        LIMIT 5
    """)
    for row in cursor:
        date, company, drug, indication = row
        drug_str = f" - {drug}" if drug else ""
        print(f"  {date}: {company}{drug_str}")

    conn.close()
    print(f"\nDatabase saved to: {DB_PATH}")


if __name__ == "__main__":
    main()
