"""ChromaDB and sentence-transformers setup for RAG search."""

import os
from pathlib import Path

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

# Persistent storage path for ChromaDB (supports Railway volume via env var)
_default_chroma_dir = Path(__file__).parent.parent / "data" / "chroma_db"
CHROMA_PERSIST_DIR = Path(os.environ.get("CHROMA_PERSIST_DIR", str(_default_chroma_dir)))

# Embedding model - using fast model for quick indexing
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Collection names for each data source
COLLECTIONS = {
    "patents": "patents",
    "grants": "grants",
    "researchers": "researchers",
    "policies": "policies",
    "fda_calendar": "fda_calendar",
}

# Singleton instances
_chroma_client = None
_embedding_function = None


def get_embedding_function():
    """Get ChromaDB's official SentenceTransformer embedding function (singleton)."""
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
    return _embedding_function


def get_chroma_client() -> chromadb.ClientAPI:
    """Get or create the ChromaDB persistent client (singleton)."""
    global _chroma_client
    if _chroma_client is None:
        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_PERSIST_DIR),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True,
            )
        )
    return _chroma_client


def get_collection(name: str) -> chromadb.Collection:
    """Get or create a collection with the embedding function."""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=name,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"}
    )


def get_all_collections() -> dict[str, chromadb.Collection]:
    """Get all RAG collections."""
    return {name: get_collection(name) for name in COLLECTIONS.values()}


def reset_collection(name: str) -> chromadb.Collection:
    """Delete and recreate a collection (for full re-indexing)."""
    client = get_chroma_client()
    try:
        client.delete_collection(name)
    except ValueError:
        pass
    return get_collection(name)
