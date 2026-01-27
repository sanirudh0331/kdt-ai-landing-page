"""
Semantic caching for Neo SQL agent.
Uses SQLite + sentence-transformers for lightweight persistent caching.
No ChromaDB dependency - simpler and easier to maintain.
"""

import os
import json
import time
import sqlite3
import hashlib
import numpy as np
from pathlib import Path
from typing import Optional

# Use sentence-transformers for embeddings (already in requirements)
from sentence_transformers import SentenceTransformer

# Cache database path (supports Railway volume via env var)
_default_cache_dir = Path(__file__).parent.parent / "data"
CACHE_DB_PATH = Path(os.environ.get("NEO_CACHE_DB", _default_cache_dir / "neo_cache.db"))

# Embedding model - same lightweight model used elsewhere
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Similarity threshold (0.0 to 1.0, higher = more similar required)
SIMILARITY_THRESHOLD = float(os.environ.get("NEO_CACHE_THRESHOLD", "0.80"))

# Cache TTL in seconds (default 1 hour)
CACHE_TTL = int(os.environ.get("NEO_CACHE_TTL", "3600"))

# Max cache entries
MAX_CACHE_ENTRIES = 500

# Singleton model
_model = None


def _get_model():
    """Get or load the embedding model (singleton)."""
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_db():
    """Get database connection, creating table if needed."""
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            embedding BLOB NOT NULL,
            answer TEXT NOT NULL,
            tool_calls TEXT,
            insights TEXT,
            cached_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_at ON cache(cached_at)")
    conn.commit()
    return conn


def _question_id(question: str) -> str:
    """Generate a stable ID for a question."""
    return hashlib.md5(question.strip().lower().encode()).hexdigest()


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def get_cached_response(question: str) -> Optional[dict]:
    """
    Check if a similar question has been answered before.

    Returns:
        dict with 'answer', 'tool_calls', 'insights' if cache hit, None otherwise
    """
    try:
        model = _get_model()
        conn = _get_db()

        # Get question embedding
        question_embedding = model.encode(question, convert_to_numpy=True)

        # Get all non-expired cache entries
        cutoff = time.time() - CACHE_TTL
        rows = conn.execute(
            "SELECT * FROM cache WHERE cached_at > ? ORDER BY cached_at DESC LIMIT 100",
            (cutoff,)
        ).fetchall()
        conn.close()

        if not rows:
            return None

        # Find most similar question
        best_match = None
        best_similarity = 0.0

        for row in rows:
            cached_embedding = np.frombuffer(row["embedding"], dtype=np.float32)
            similarity = _cosine_similarity(question_embedding, cached_embedding)

            if similarity > best_similarity:
                best_similarity = similarity
                best_match = row

        if best_similarity < SIMILARITY_THRESHOLD:
            return None

        # Cache hit!
        return {
            "answer": best_match["answer"],
            "tool_calls": json.loads(best_match["tool_calls"] or "[]"),
            "insights": json.loads(best_match["insights"] or "[]"),
            "cached": True,
            "similarity": round(best_similarity, 3),
            "original_question": best_match["question"],
        }

    except Exception as e:
        print(f"Cache lookup error: {e}")
        return None


def cache_response(question: str, answer: str, tool_calls: list, insights: list):
    """
    Cache a question-response pair for future similarity matching.
    """
    try:
        model = _get_model()
        conn = _get_db()

        # Check cache size and cleanup if needed
        count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        if count >= MAX_CACHE_ENTRIES:
            _cleanup_old_entries(conn)

        # Get embedding
        embedding = model.encode(question, convert_to_numpy=True)
        embedding_bytes = embedding.astype(np.float32).tobytes()

        question_id = _question_id(question)

        # Upsert
        conn.execute("""
            INSERT OR REPLACE INTO cache (id, question, embedding, answer, tool_calls, insights, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            question_id,
            question,
            embedding_bytes,
            answer[:10000],  # Limit answer size
            json.dumps(tool_calls[:20]),
            json.dumps(insights[:10]),
            time.time(),
        ))
        conn.commit()
        conn.close()

    except Exception as e:
        print(f"Cache write error: {e}")


def _cleanup_old_entries(conn):
    """Remove oldest entries when cache is full."""
    try:
        # Delete oldest half
        conn.execute("""
            DELETE FROM cache WHERE id IN (
                SELECT id FROM cache ORDER BY cached_at ASC LIMIT ?
            )
        """, (MAX_CACHE_ENTRIES // 2,))
        conn.commit()
    except Exception as e:
        print(f"Cache cleanup error: {e}")


def clear_cache():
    """Clear all cached responses."""
    try:
        if CACHE_DB_PATH.exists():
            conn = _get_db()
            conn.execute("DELETE FROM cache")
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Cache clear error: {e}")


def get_cache_stats() -> dict:
    """Get cache statistics."""
    try:
        conn = _get_db()
        count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        conn.close()
        return {
            "entries": count,
            "max_entries": MAX_CACHE_ENTRIES,
            "ttl_seconds": CACHE_TTL,
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "db_path": str(CACHE_DB_PATH),
        }
    except Exception as e:
        return {"error": str(e)}
