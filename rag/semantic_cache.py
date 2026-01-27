"""
Semantic caching for Neo SQL agent.
Caches question-response pairs and retrieves similar questions to avoid redundant LLM calls.
Uses ChromaDB for vector similarity search.
"""

import os
import json
import time
import hashlib
from typing import Optional

try:
    from embeddings import get_chroma_client, get_embedding_function
except ImportError:
    from rag.embeddings import get_chroma_client, get_embedding_function

# Cache collection name
CACHE_COLLECTION = "neo_query_cache"

# Similarity threshold (0.0 to 1.0, higher = more similar required)
# 0.85 is fairly strict - only very similar questions match
SIMILARITY_THRESHOLD = float(os.environ.get("NEO_CACHE_THRESHOLD", "0.85"))

# Cache TTL in seconds (default 1 hour)
CACHE_TTL = int(os.environ.get("NEO_CACHE_TTL", "3600"))

# Max cache entries before cleanup
MAX_CACHE_ENTRIES = 500


def _get_cache_collection():
    """Get or create the semantic cache collection."""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=CACHE_COLLECTION,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"}
    )


def _question_id(question: str) -> str:
    """Generate a stable ID for a question."""
    return hashlib.md5(question.strip().lower().encode()).hexdigest()


def get_cached_response(question: str) -> Optional[dict]:
    """
    Check if a similar question has been answered before.

    Returns:
        dict with 'answer', 'tool_calls', 'insights' if cache hit, None otherwise
    """
    try:
        collection = _get_cache_collection()

        # Query for similar questions
        results = collection.query(
            query_texts=[question],
            n_results=1,
            include=["documents", "metadatas", "distances"]
        )

        if not results["ids"] or not results["ids"][0]:
            return None

        # Check similarity (ChromaDB returns distance, not similarity for cosine)
        # For cosine distance: similarity = 1 - distance
        distance = results["distances"][0][0]
        similarity = 1 - distance

        if similarity < SIMILARITY_THRESHOLD:
            return None

        # Check TTL
        metadata = results["metadatas"][0][0]
        cached_at = metadata.get("cached_at", 0)
        if time.time() - cached_at > CACHE_TTL:
            # Expired - remove from cache
            collection.delete(ids=[results["ids"][0][0]])
            return None

        # Cache hit!
        return {
            "answer": metadata.get("answer", ""),
            "tool_calls": json.loads(metadata.get("tool_calls", "[]")),
            "insights": json.loads(metadata.get("insights", "[]")),
            "cached": True,
            "similarity": round(similarity, 3),
            "original_question": results["documents"][0][0],
        }

    except Exception as e:
        # Don't let cache errors break the main flow
        print(f"Cache lookup error: {e}")
        return None


def cache_response(question: str, answer: str, tool_calls: list, insights: list):
    """
    Cache a question-response pair for future similarity matching.
    """
    try:
        collection = _get_cache_collection()

        # Check cache size and cleanup if needed
        if collection.count() >= MAX_CACHE_ENTRIES:
            _cleanup_old_entries(collection)

        question_id = _question_id(question)

        # Upsert (update if exists, insert if not)
        collection.upsert(
            ids=[question_id],
            documents=[question],
            metadatas=[{
                "answer": answer[:10000],  # Limit answer size
                "tool_calls": json.dumps(tool_calls[:20]),  # Limit tool calls
                "insights": json.dumps(insights[:10]),
                "cached_at": time.time(),
            }]
        )

    except Exception as e:
        print(f"Cache write error: {e}")


def _cleanup_old_entries(collection):
    """Remove oldest entries when cache is full."""
    try:
        # Get all entries with metadata
        all_items = collection.get(include=["metadatas"])

        if not all_items["ids"]:
            return

        # Sort by cached_at and remove oldest half
        entries = list(zip(all_items["ids"], all_items["metadatas"]))
        entries.sort(key=lambda x: x[1].get("cached_at", 0))

        to_remove = [entry[0] for entry in entries[:len(entries) // 2]]
        if to_remove:
            collection.delete(ids=to_remove)

    except Exception as e:
        print(f"Cache cleanup error: {e}")


def clear_cache():
    """Clear all cached responses."""
    try:
        client = get_chroma_client()
        try:
            client.delete_collection(CACHE_COLLECTION)
        except ValueError:
            pass
    except Exception as e:
        print(f"Cache clear error: {e}")


def get_cache_stats() -> dict:
    """Get cache statistics."""
    try:
        collection = _get_cache_collection()
        return {
            "entries": collection.count(),
            "max_entries": MAX_CACHE_ENTRIES,
            "ttl_seconds": CACHE_TTL,
            "similarity_threshold": SIMILARITY_THRESHOLD,
        }
    except Exception as e:
        return {"error": str(e)}
