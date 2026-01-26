"""Data ingestion scripts for RAG search.

Fetches data from KdT AI tool APIs and stores embeddings in ChromaDB.
Supports checkpointing for resumable ingestion on rate limit errors.
"""

import os
import json
import httpx
from pathlib import Path
from typing import Generator
from datetime import datetime

try:
    from embeddings import (
        get_collection, reset_collection, COLLECTIONS, CHROMA_PERSIST_DIR
    )
except ImportError:
    from rag.embeddings import (
        get_collection, reset_collection, COLLECTIONS, CHROMA_PERSIST_DIR
    )

# Batch size for embedding operations
BATCH_SIZE = 100

# Checkpoint file path (in the same directory as ChromaDB data)
CHECKPOINT_FILE = CHROMA_PERSIST_DIR / "ingest_checkpoint.json"


def load_checkpoint() -> dict:
    """Load ingestion checkpoint from file."""
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_updated": None, "sources": {}}


def save_checkpoint(source: str, last_id: str, count: int, error: str = None):
    """Save ingestion progress checkpoint."""
    checkpoint = load_checkpoint()
    checkpoint["last_updated"] = datetime.now().isoformat()
    checkpoint["sources"][source] = {
        "last_id": last_id,
        "count": count,
        "timestamp": datetime.now().isoformat(),
        "error": error
    }
    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(checkpoint, f, indent=2)


def clear_checkpoint(source: str = None):
    """Clear checkpoint for a source or all sources."""
    if source:
        checkpoint = load_checkpoint()
        if source in checkpoint.get("sources", {}):
            del checkpoint["sources"][source]
            with open(CHECKPOINT_FILE, "w") as f:
                json.dump(checkpoint, f, indent=2)
    elif CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()

# Service URLs - use Railway internal networking if available
SERVICE_URLS = {
    "patents": os.environ.get("PATENT_SERVICE_URL", "https://patentwarrior.up.railway.app"),
    "grants": os.environ.get("GRANTS_SERVICE_URL", "https://grants-tracker-production.up.railway.app"),
    "policies": os.environ.get("POLICY_SERVICE_URL", "https://policywatch.up.railway.app"),
}


def chunk_text(text: str, max_chars: int = 1500, overlap: int = 200) -> list[dict]:
    """Split text into overlapping chunks with position tracking.

    Args:
        text: The text to chunk
        max_chars: Maximum characters per chunk (default 1500 for better context)
        overlap: Characters to overlap between chunks (default 200)

    Returns:
        List of dicts with 'text', 'chunk_index', and 'total_chunks' keys
    """
    if len(text) <= max_chars:
        return [{"text": text, "chunk_index": 0, "total_chunks": 1}]

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = min(start + max_chars, len(text))

        # Find sentence boundary if not at end of text
        if end < len(text):
            # Look for sentence boundary in the latter half of the chunk
            boundary = text.rfind('. ', start + max_chars // 2, end)
            if boundary > start:
                end = boundary + 1

        chunk_text_content = text[start:end].strip()
        if chunk_text_content:
            chunks.append({
                "text": chunk_text_content,
                "chunk_index": chunk_index,
            })
            chunk_index += 1

        # Move start position, accounting for overlap
        start = end - overlap if end < len(text) else len(text)

    # Add total_chunks to each chunk
    for c in chunks:
        c["total_chunks"] = len(chunks)

    return chunks


def fetch_from_api(source: str) -> list[dict]:
    """Fetch data from a service's /api/export endpoint."""
    url = SERVICE_URLS.get(source)
    if not url:
        print(f"  Warning: No URL configured for {source}")
        return []

    try:
        print(f"  Fetching from {url}/api/export...")
        with httpx.Client(timeout=120.0) as client:
            response = client.get(f"{url}/api/export")
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
    except Exception as e:
        print(f"  Error fetching {source}: {e}")
        return []


# ============ PATENTS ============

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

    patents = fetch_from_api("patents")
    if not patents:
        if verbose:
            print("  No patents fetched")
        return 0

    batch_ids, batch_documents, batch_metadatas = [], [], []
    total_indexed, skipped = 0, 0

    for patent in patents:
        doc_id = f"patent_{patent['id']}"

        if doc_id in existing_ids:
            skipped += 1
            continue

        text_parts = [patent.get("title", "")]
        if patent.get("abstract"):
            text_parts.append(patent["abstract"])

        document = " ".join(text_parts)
        chunks = chunk_text(document)

        for chunk_data in chunks:
            chunk_idx = chunk_data["chunk_index"]
            chunk_id = f"{doc_id}_chunk{chunk_idx}" if chunk_data["total_chunks"] > 1 else doc_id

            metadata = {
                "source": "patents",
                "patent_id": str(patent["id"]),
                "patent_number": patent.get("patent_number", ""),
                "title": (patent.get("title", "") or "")[:500],
                "grant_date": patent.get("grant_date", ""),
                "assignee": patent.get("primary_assignee", ""),
                "cpc_codes": patent.get("cpc_codes", ""),
                "chunk_index": chunk_idx,
                "total_chunks": chunk_data["total_chunks"],
            }

            batch_ids.append(chunk_id)
            batch_documents.append(chunk_data["text"])
            batch_metadatas.append(metadata)

            if len(batch_ids) >= BATCH_SIZE:
                try:
                    collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
                    total_indexed += len(batch_ids)
                    if verbose:
                        print(f"    Indexed {total_indexed} patents...")
                except Exception as e:
                    # Save checkpoint on failure
                    last_id = batch_ids[-1] if batch_ids else ""
                    save_checkpoint("patents", last_id, total_indexed, str(e))
                    if verbose:
                        print(f"  Error during batch: {e}")
                        print(f"  Checkpoint saved at {total_indexed} documents")
                    raise
                batch_ids, batch_documents, batch_metadatas = [], [], []

    if batch_ids:
        try:
            collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
            total_indexed += len(batch_ids)
        except Exception as e:
            # Save checkpoint on failure
            last_id = batch_ids[-1] if batch_ids else ""
            save_checkpoint("patents", last_id, total_indexed, str(e))
            if verbose:
                print(f"  Error during final batch: {e}")
                print(f"  Checkpoint saved. Resume with --resume flag")
            raise

    if verbose:
        print(f"  Patents: {total_indexed} indexed, {skipped} skipped")

    # Clear checkpoint on success
    clear_checkpoint("patents")
    return total_indexed


# ============ GRANTS ============

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

    grants = fetch_from_api("grants")
    if not grants:
        if verbose:
            print("  No grants fetched")
        return 0

    batch_ids, batch_documents, batch_metadatas = [], [], []
    total_indexed, skipped = 0, 0

    for grant in grants:
        doc_id = f"grant_{grant['id']}"

        if doc_id in existing_ids:
            skipped += 1
            continue

        text_parts = [grant.get("title", "")]
        if grant.get("abstract"):
            text_parts.append(grant["abstract"])

        document = " ".join(text_parts)
        chunks = chunk_text(document)

        for chunk_data in chunks:
            chunk_idx = chunk_data["chunk_index"]
            chunk_id = f"{doc_id}_chunk{chunk_idx}" if chunk_data["total_chunks"] > 1 else doc_id

            metadata = {
                "source": "grants",
                "grant_id": str(grant["id"]),
                "title": (grant.get("title", "") or "")[:500],
                "agency": grant.get("agency", ""),
                "mechanism": grant.get("mechanism", ""),
                "total_cost": str(grant.get("total_cost", "")),
                "award_date": grant.get("award_notice_date", ""),
                "chunk_index": chunk_idx,
                "total_chunks": chunk_data["total_chunks"],
            }

            batch_ids.append(chunk_id)
            batch_documents.append(chunk_data["text"])
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


# ============ POLICIES ============

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

    policies = fetch_from_api("policies")
    if not policies:
        if verbose:
            print("  No policies fetched")
        return 0

    batch_ids, batch_documents, batch_metadatas = [], [], []
    total_indexed, skipped = 0, 0

    for policy in policies:
        doc_id = f"policy_{policy['id']}"

        if doc_id in existing_ids:
            skipped += 1
            continue

        text_parts = [policy.get("title", "")]
        if policy.get("summary"):
            text_parts.append(policy["summary"])
        if policy.get("impact_summary"):
            text_parts.append(policy["impact_summary"])

        document = " ".join(text_parts)
        chunks = chunk_text(document)

        for chunk_data in chunks:
            chunk_idx = chunk_data["chunk_index"]
            chunk_id = f"{doc_id}_chunk{chunk_idx}" if chunk_data["total_chunks"] > 1 else doc_id

            metadata = {
                "source": "policies",
                "policy_id": str(policy["id"]),
                "title": (policy.get("title", "") or "")[:500],
                "relevance_score": str(policy.get("relevance_score", "")),
                "passage_likelihood": policy.get("passage_likelihood", ""),
                "status": policy.get("status", ""),
                "chunk_index": chunk_idx,
                "total_chunks": chunk_data["total_chunks"],
            }

            batch_ids.append(chunk_id)
            batch_documents.append(chunk_data["text"])
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

def ingest_fda_calendar(reset: bool = False, verbose: bool = True) -> int:
    """Ingest FDA calendar events into ChromaDB."""
    collection_name = COLLECTIONS["fda_calendar"]

    if reset:
        if verbose:
            print(f"Resetting collection: {collection_name}")
        collection = reset_collection(collection_name)
    else:
        collection = get_collection(collection_name)

    # FDA calendar is stored locally in the landing page repo
    fda_path = Path(__file__).parent.parent / "static" / "fda-calendar.json"
    if not fda_path.exists():
        if verbose:
            print(f"  Warning: FDA calendar not found at {fda_path}")
        return 0

    with open(fda_path, "r") as f:
        data = json.load(f)

    events = data.get("events", [])

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

    for i, event in enumerate(events):
        doc_id = f"fda_{i}"

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
            "event_id": str(i),
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
    elif args.source == "policies":
        ingest_policies(reset=args.reset)
    elif args.source == "fda_calendar":
        ingest_fda_calendar(reset=args.reset)
