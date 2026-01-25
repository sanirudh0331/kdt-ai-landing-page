"""ChromaDB and sentence-transformers setup for RAG search."""

import os
from pathlib import Path
from functools import lru_cache

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

# Persistent storage path for ChromaDB
CHROMA_PERSIST_DIR = Path(__file__).parent.parent / "data" / "chroma_db"

# Embedding model - using fast model for quick indexing
# Options: "all-MiniLM-L6-v2" (fast, 80MB) or "BAAI/bge-large-en-v1.5" (better quality, 1.3GB)
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Collection names for each data source
COLLECTIONS = {
    "patents": "patents",
    "grants": "grants",
    "researchers": "researchers",
    "policies": "policies",
    "fda_calendar": "fda_calendar",
}


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """Load the sentence transformer model (cached singleton)."""
    return SentenceTransformer(EMBEDDING_MODEL)


class SentenceTransformerEmbeddingFunction:
    """Custom embedding function for ChromaDB using sentence-transformers."""

    def __init__(self):
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = get_embedding_model()
        return self._model

    def name(self) -> str:
        """Return the name of the embedding function (required by ChromaDB)."""
        return EMBEDDING_MODEL

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        embeddings = self.model.encode(input, normalize_embeddings=True)
        return embeddings.tolist()


@lru_cache(maxsize=1)
def get_embedding_function() -> SentenceTransformerEmbeddingFunction:
    """Get the embedding function (cached singleton)."""
    return SentenceTransformerEmbeddingFunction()


def get_chroma_client() -> chromadb.ClientAPI:
    """Get or create the ChromaDB persistent client."""
    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    return chromadb.PersistentClient(
        path=str(CHROMA_PERSIST_DIR),
        settings=Settings(
            anonymized_telemetry=False,
            allow_reset=True,
        )
    )


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
