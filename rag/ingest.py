"""Data ingestion scripts for RAG search.

Fetches data from all KdT AI tool databases and stores embeddings in ChromaDB.
"""

import sqlite3
import json
from pathlib import Path
from typing import Generator

from rag.embeddings import (
    get_collection, reset_collection, COLLECTIONS, DATABASE_PATHS, CHROMA_PERSIST_DIR
)

# Batch size for embedding operations
BATCH_SIZE = 100


def chunk_text(text: str, max_chars: int = 2000) -> list[str]:
    """Split text into chunks if it exceeds max_chars."""
    if len(text) <= max_chars:
        return [text]

    sentences = text.replace(". ", ".|").split("|")
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_chars:
            current_chunk += sentence + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks if chunks else [text[:max_chars]]


# ============ PATENTS ============

def fetch_patents() -> Generator[dict, None, None]:
    """Fetch all patents from the Patent Warrior database."""
    db_path = DATABASE_PATHS["patents"]
    if not db_path.exists():
        print(f"  Warning: Patents database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, patent_number, title, abstract, grant_date, primary_assignee, cpc_codes, patent_type
        FROM patents WHERE title IS NOT NULL
    """)

    for row in cursor:
        yield dict(row)

    conn.close()


def ingest_patents(reset: bool = False, verbose: bool = True) -> int:
    """Ingest patents into ChromaDB."""
    collection_name = COLLECTIONS["patents"]

    if reset:
        if verbose:
            print(f"Resetting collection: {collection_name}")
        collection = reset_collection(collection_name)
    else:
        collection = get_collection(collection_name)

    existing_ids = set()
    if not reset:
        try:
            existing = collection.get()
            existing_ids = set(existing["ids"]) if existing["ids"] else set()
            if verbose:
                print(f"  Found {len(existing_ids)} existing documents")
        except Exception:
            pass

    batch_ids, batch_documents, batch_metadatas = [], [], []
    total_indexed, skipped = 0, 0

    if verbose:
        print("  Fetching patents from database...")

    for patent in fetch_patents():
        doc_id = f"patent_{patent['id']}"

        if doc_id in existing_ids:
            skipped += 1
            continue

        text_parts = [patent["title"]]
        if patent["abstract"]:
            text_parts.append(patent["abstract"])

        document = " ".join(text_parts)
        chunks = chunk_text(document)

        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk{i}" if len(chunks) > 1 else doc_id

            metadata = {
                "source": "patents",
                "patent_id": patent["id"],
                "patent_number": patent["patent_number"] or "",
                "title": patent["title"][:500] if patent["title"] else "",
                "grant_date": patent["grant_date"] or "",
                "assignee": patent["primary_assignee"] or "",
                "cpc_codes": patent["cpc_codes"] or "",
            }

            batch_ids.append(chunk_id)
            batch_documents.append(chunk)
            batch_metadatas.append(metadata)

            if len(batch_ids) >= BATCH_SIZE:
                collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
                total_indexed += len(batch_ids)
                if verbose:
                    print(f"    Indexed {total_indexed} patents...")
                batch_ids, batch_documents, batch_metadatas = [], [], []

    if batch_ids:
        collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
        total_indexed += len(batch_ids)

    if verbose:
        print(f"  Patents: {total_indexed} indexed, {skipped} skipped")

    return total_indexed


# ============ GRANTS ============

def fetch_grants() -> Generator[dict, None, None]:
    """Fetch all grants from the Grants Tracker database."""
    db_path = DATABASE_PATHS["grants"]
    if not db_path.exists():
        print(f"  Warning: Grants database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, abstract, agency, mechanism, total_cost, keywords, mesh_terms, award_notice_date
        FROM grants WHERE title IS NOT NULL
    """)

    for row in cursor:
        yield dict(row)

    conn.close()


def ingest_grants(reset: bool = False, verbose: bool = True) -> int:
    """Ingest grants into ChromaDB."""
    collection_name = COLLECTIONS["grants"]

    if reset:
        if verbose:
            print(f"Resetting collection: {collection_name}")
        collection = reset_collection(collection_name)
    else:
        collection = get_collection(collection_name)

    existing_ids = set()
    if not reset:
        try:
            existing = collection.get()
            existing_ids = set(existing["ids"]) if existing["ids"] else set()
            if verbose:
                print(f"  Found {len(existing_ids)} existing documents")
        except Exception:
            pass

    batch_ids, batch_documents, batch_metadatas = [], [], []
    total_indexed, skipped = 0, 0

    if verbose:
        print("  Fetching grants from database...")

    for grant in fetch_grants():
        doc_id = f"grant_{grant['id']}"

        if doc_id in existing_ids:
            skipped += 1
            continue

        text_parts = [grant["title"]]
        if grant["abstract"]:
            text_parts.append(grant["abstract"])

        document = " ".join(text_parts)
        chunks = chunk_text(document)

        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk{i}" if len(chunks) > 1 else doc_id

            metadata = {
                "source": "grants",
                "grant_id": str(grant["id"]),
                "title": grant["title"][:500] if grant["title"] else "",
                "agency": grant["agency"] or "",
                "mechanism": grant["mechanism"] or "",
                "total_cost": str(grant["total_cost"]) if grant["total_cost"] else "",
                "award_date": grant["award_notice_date"] or "",
            }

            batch_ids.append(chunk_id)
            batch_documents.append(chunk)
            batch_metadatas.append(metadata)

            if len(batch_ids) >= BATCH_SIZE:
                collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
                total_indexed += len(batch_ids)
                if verbose:
                    print(f"    Indexed {total_indexed} grants...")
                batch_ids, batch_documents, batch_metadatas = [], [], []

    if batch_ids:
        collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
        total_indexed += len(batch_ids)

    if verbose:
        print(f"  Grants: {total_indexed} indexed, {skipped} skipped")

    return total_indexed


# ============ RESEARCHERS ============

def fetch_researchers() -> Generator[dict, None, None]:
    """Fetch all researchers from the H-Index Tracker database."""
    db_path = DATABASE_PATHS["researchers"]
    if not db_path.exists():
        print(f"  Warning: Researchers database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, h_index, i10_index, works_count, cited_by_count, topics, affiliations, institutions
        FROM researchers WHERE name IS NOT NULL
    """)

    for row in cursor:
        yield dict(row)

    conn.close()


def ingest_researchers(reset: bool = False, verbose: bool = True) -> int:
    """Ingest researchers into ChromaDB."""
    collection_name = COLLECTIONS["researchers"]

    if reset:
        if verbose:
            print(f"Resetting collection: {collection_name}")
        collection = reset_collection(collection_name)
    else:
        collection = get_collection(collection_name)

    existing_ids = set()
    if not reset:
        try:
            existing = collection.get()
            existing_ids = set(existing["ids"]) if existing["ids"] else set()
            if verbose:
                print(f"  Found {len(existing_ids)} existing documents")
        except Exception:
            pass

    batch_ids, batch_documents, batch_metadatas = [], [], []
    total_indexed, skipped = 0, 0

    if verbose:
        print("  Fetching researchers from database...")

    for researcher in fetch_researchers():
        doc_id = f"researcher_{researcher['id']}"

        if doc_id in existing_ids:
            skipped += 1
            continue

        # Build searchable text from name, topics, and affiliations
        text_parts = [researcher["name"]]
        if researcher["topics"]:
            try:
                topics = json.loads(researcher["topics"]) if isinstance(researcher["topics"], str) else researcher["topics"]
                if isinstance(topics, list):
                    text_parts.extend(topics[:10])  # Top 10 topics
            except (json.JSONDecodeError, TypeError):
                pass
        if researcher["affiliations"]:
            try:
                affiliations = json.loads(researcher["affiliations"]) if isinstance(researcher["affiliations"], str) else researcher["affiliations"]
                if isinstance(affiliations, list):
                    text_parts.extend(affiliations[:5])  # Top 5 affiliations
            except (json.JSONDecodeError, TypeError):
                pass

        document = " ".join(str(p) for p in text_parts if p)

        metadata = {
            "source": "researchers",
            "researcher_id": str(researcher["id"]),
            "name": researcher["name"],
            "h_index": str(researcher["h_index"]) if researcher["h_index"] else "",
            "works_count": str(researcher["works_count"]) if researcher["works_count"] else "",
            "cited_by_count": str(researcher["cited_by_count"]) if researcher["cited_by_count"] else "",
        }

        batch_ids.append(doc_id)
        batch_documents.append(document)
        batch_metadatas.append(metadata)

        if len(batch_ids) >= BATCH_SIZE:
            collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
            total_indexed += len(batch_ids)
            if verbose:
                print(f"    Indexed {total_indexed} researchers...")
            batch_ids, batch_documents, batch_metadatas = [], [], []

    if batch_ids:
        collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
        total_indexed += len(batch_ids)

    if verbose:
        print(f"  Researchers: {total_indexed} indexed, {skipped} skipped")

    return total_indexed


# ============ POLICIES ============

def fetch_policies() -> Generator[dict, None, None]:
    """Fetch all policies from the Policy Tracker database."""
    db_path = DATABASE_PATHS["policies"]
    if not db_path.exists():
        print(f"  Warning: Policies database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, bill_id, title, summary, relevance_score, sector_tags, impact_summary, passage_likelihood
        FROM bills WHERE title IS NOT NULL
    """)

    for row in cursor:
        yield dict(row)

    conn.close()


def ingest_policies(reset: bool = False, verbose: bool = True) -> int:
    """Ingest policies into ChromaDB."""
    collection_name = COLLECTIONS["policies"]

    if reset:
        if verbose:
            print(f"Resetting collection: {collection_name}")
        collection = reset_collection(collection_name)
    else:
        collection = get_collection(collection_name)

    existing_ids = set()
    if not reset:
        try:
            existing = collection.get()
            existing_ids = set(existing["ids"]) if existing["ids"] else set()
            if verbose:
                print(f"  Found {len(existing_ids)} existing documents")
        except Exception:
            pass

    batch_ids, batch_documents, batch_metadatas = [], [], []
    total_indexed, skipped = 0, 0

    if verbose:
        print("  Fetching policies from database...")

    for policy in fetch_policies():
        doc_id = f"policy_{policy['id']}"

        if doc_id in existing_ids:
            skipped += 1
            continue

        text_parts = [policy["title"]]
        if policy["summary"]:
            text_parts.append(policy["summary"])
        if policy["impact_summary"]:
            text_parts.append(policy["impact_summary"])

        document = " ".join(text_parts)
        chunks = chunk_text(document)

        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk{i}" if len(chunks) > 1 else doc_id

            metadata = {
                "source": "policies",
                "policy_id": str(policy["id"]),
                "bill_id": policy["bill_id"] or "",
                "title": policy["title"][:500] if policy["title"] else "",
                "relevance_score": str(policy["relevance_score"]) if policy["relevance_score"] else "",
                "passage_likelihood": policy["passage_likelihood"] or "",
            }

            batch_ids.append(chunk_id)
            batch_documents.append(chunk)
            batch_metadatas.append(metadata)

            if len(batch_ids) >= BATCH_SIZE:
                collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
                total_indexed += len(batch_ids)
                if verbose:
                    print(f"    Indexed {total_indexed} policies...")
                batch_ids, batch_documents, batch_metadatas = [], [], []

    if batch_ids:
        collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
        total_indexed += len(batch_ids)

    if verbose:
        print(f"  Policies: {total_indexed} indexed, {skipped} skipped")

    return total_indexed


# ============ FDA CALENDAR ============

def fetch_fda_events() -> Generator[dict, None, None]:
    """Fetch FDA calendar events from the JSON file."""
    fda_path = Path(__file__).parent.parent / "static" / "fda-calendar.json"
    if not fda_path.exists():
        print(f"  Warning: FDA calendar not found at {fda_path}")
        return

    with open(fda_path, "r") as f:
        data = json.load(f)

    events = data.get("events", [])
    for i, event in enumerate(events):
        event["id"] = i
        yield event


def ingest_fda_calendar(reset: bool = False, verbose: bool = True) -> int:
    """Ingest FDA calendar events into ChromaDB."""
    collection_name = COLLECTIONS["fda_calendar"]

    if reset:
        if verbose:
            print(f"Resetting collection: {collection_name}")
        collection = reset_collection(collection_name)
    else:
        collection = get_collection(collection_name)

    existing_ids = set()
    if not reset:
        try:
            existing = collection.get()
            existing_ids = set(existing["ids"]) if existing["ids"] else set()
            if verbose:
                print(f"  Found {len(existing_ids)} existing documents")
        except Exception:
            pass

    batch_ids, batch_documents, batch_metadatas = [], [], []
    total_indexed, skipped = 0, 0

    if verbose:
        print("  Fetching FDA events from JSON...")

    for event in fetch_fda_events():
        doc_id = f"fda_{event['id']}"

        if doc_id in existing_ids:
            skipped += 1
            continue

        text_parts = []
        if event.get("company"):
            text_parts.append(event["company"])
        if event.get("drug"):
            text_parts.append(event["drug"])
        if event.get("indication"):
            text_parts.append(event["indication"])

        if not text_parts:
            continue

        document = " ".join(text_parts)

        metadata = {
            "source": "fda_calendar",
            "event_id": str(event["id"]),
            "company": event.get("company", ""),
            "ticker": event.get("ticker", ""),
            "drug": event.get("drug", ""),
            "indication": event.get("indication", ""),
            "date": event.get("date", ""),
            "type": event.get("type", ""),
        }

        batch_ids.append(doc_id)
        batch_documents.append(document)
        batch_metadatas.append(metadata)

        if len(batch_ids) >= BATCH_SIZE:
            collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
            total_indexed += len(batch_ids)
            batch_ids, batch_documents, batch_metadatas = [], [], []

    if batch_ids:
        collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
        total_indexed += len(batch_ids)

    if verbose:
        print(f"  FDA Calendar: {total_indexed} indexed, {skipped} skipped")

    return total_indexed


# ============ MAIN INGESTION ============

def get_collection_stats() -> dict:
    """Get statistics about all collections."""
    stats = {}
    for source, name in COLLECTIONS.items():
        try:
            collection = get_collection(name)
            stats[source] = collection.count()
        except Exception as e:
            stats[source] = f"Error: {e}"
    return stats


def ingest_all(reset: bool = False, verbose: bool = True) -> dict:
    """Ingest data from all sources."""
    if verbose:
        print("\n" + "=" * 50)
        print("KdT AI RAG Search - Data Ingestion")
        print("=" * 50 + "\n")

    results = {}

    print("Ingesting patents...")
    results["patents"] = ingest_patents(reset=reset, verbose=verbose)

    print("\nIngesting grants...")
    results["grants"] = ingest_grants(reset=reset, verbose=verbose)

    print("\nIngesting researchers...")
    results["researchers"] = ingest_researchers(reset=reset, verbose=verbose)

    print("\nIngesting policies...")
    results["policies"] = ingest_policies(reset=reset, verbose=verbose)

    print("\nIngesting FDA calendar...")
    results["fda_calendar"] = ingest_fda_calendar(reset=reset, verbose=verbose)

    if verbose:
        print("\n" + "=" * 50)
        print("Ingestion Complete!")
        print("=" * 50)
        print("\nCollection Statistics:")
        for source, count in get_collection_stats().items():
            print(f"  {source}: {count}")
        print()

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest data into RAG search")
    parser.add_argument("--reset", action="store_true", help="Reset and re-index all data")
    parser.add_argument("--source", choices=list(COLLECTIONS.keys()) + ["all"],
                       default="all", help="Data source to ingest")
    parser.add_argument("--stats", action="store_true", help="Show collection statistics")

    args = parser.parse_args()

    if args.stats:
        print("\nCollection Statistics:")
        print("-" * 30)
        for source, count in get_collection_stats().items():
            print(f"  {source}: {count}")
        print()
    elif args.source == "all":
        ingest_all(reset=args.reset)
    elif args.source == "patents":
        ingest_patents(reset=args.reset)
    elif args.source == "grants":
        ingest_grants(reset=args.reset)
    elif args.source == "researchers":
        ingest_researchers(reset=args.reset)
    elif args.source == "policies":
        ingest_policies(reset=args.reset)
    elif args.source == "fda_calendar":
        ingest_fda_calendar(reset=args.reset)
