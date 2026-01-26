"""RAG search and reranking logic."""

from typing import Optional
from dataclasses import dataclass, asdict

from sentence_transformers import CrossEncoder

try:
    from embeddings import get_collection, get_embedding_function, COLLECTIONS
except ImportError:
    from rag.embeddings import get_collection, get_embedding_function, COLLECTIONS


# Cross-encoder reranker (singleton)
_reranker = None


def get_reranker():
    """Get or initialize the cross-encoder reranker (singleton)."""
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    return _reranker


# Tool URLs (Railway deployments)
TOOL_URLS = {
    "patents": "https://patentwarrior.up.railway.app",
    "grants": "https://grants-tracker-production.up.railway.app",
    "researchers": "https://h-index-tracker-production.up.railway.app",
    "policies": "https://policy-tracker-production.up.railway.app",
    "fda_calendar": "#fda",  # Anchor on landing page
}


@dataclass
class SearchResult:
    """A single search result."""
    id: str
    source: str
    title: str
    snippet: str
    score: float
    metadata: dict
    url: str

    def to_dict(self) -> dict:
        return asdict(self)


def rerank_results(query: str, results: list[SearchResult], top_k: int = 10) -> list[SearchResult]:
    """Rerank search results using Cross-Encoder for better relevance."""
    if not results or len(results) <= 1:
        return results

    reranker = get_reranker()
    pairs = [(query, r.snippet + " " + r.title) for r in results]
    scores = reranker.predict(pairs)

    for i, result in enumerate(results):
        result.score = float(scores[i])  # Replace embedding score with rerank score

    results.sort(key=lambda x: x.score, reverse=True)
    return results[:top_k]


def generate_url(source: str, metadata: dict) -> str:
    """Generate deep link URL for a search result."""
    base_url = TOOL_URLS.get(source, "#")

    if source == "patents":
        patent_id = metadata.get("patent_id", "")
        return f"{base_url}/patent/{patent_id}"
    elif source == "grants":
        grant_id = metadata.get("grant_id", "")
        return f"{base_url}/grant/{grant_id}"
    elif source == "researchers":
        researcher_id = metadata.get("researcher_id", "")
        return f"{base_url}/researcher/{researcher_id}"
    elif source == "policies":
        policy_id = metadata.get("policy_id", "")
        bill_id = metadata.get("bill_id", "")
        return f"{base_url}/bill/{bill_id or policy_id}"
    elif source == "fda_calendar":
        return "#fda"

    return base_url


def get_display_title(source: str, metadata: dict) -> str:
    """Generate a display title based on source type."""
    if source == "patents":
        return metadata.get("title", "Untitled Patent")
    elif source == "grants":
        return metadata.get("title", "Untitled Grant")
    elif source == "researchers":
        name = metadata.get("name", "Unknown Researcher")
        h_index = metadata.get("h_index", "")
        return f"{name}" + (f" (h-index: {h_index})" if h_index else "")
    elif source == "policies":
        return metadata.get("title", "Untitled Policy")
    elif source == "fda_calendar":
        company = metadata.get("company", "")
        drug = metadata.get("drug", "")
        return f"{company} - {drug}" if drug else company

    return metadata.get("title", "Untitled")


def search_collection(
    query: str,
    collection_name: str,
    n_results: int = 10,
    where: Optional[dict] = None,
) -> list[SearchResult]:
    """Search a single collection."""
    collection = get_collection(collection_name)

    if collection.count() == 0:
        return []

    # Compute embedding ourselves to avoid ChromaDB callback issues
    embedding_fn = get_embedding_function()
    query_embedding = embedding_fn([query])[0]

    query_params = {
        "query_embeddings": [query_embedding],
        "n_results": min(n_results, collection.count()),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        query_params["where"] = where

    results = collection.query(**query_params)

    search_results = []
    if results and results["ids"] and results["ids"][0]:
        ids = results["ids"][0]
        documents = results["documents"][0] if results["documents"] else [None] * len(ids)
        metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(ids)
        distances = results["distances"][0] if results["distances"] else [0] * len(ids)

        for i, doc_id in enumerate(ids):
            metadata = metadatas[i] if metadatas[i] else {}
            source = metadata.get("source", collection_name)

            # Convert distance to similarity score (cosine distance: similarity = 1 - distance)
            distance = distances[i] if distances[i] else 0
            score = max(0, 1 - distance)

            doc = documents[i] if documents[i] else ""
            title = get_display_title(source, metadata)
            snippet = doc[:300] + "..." if len(doc) > 300 else doc

            search_results.append(SearchResult(
                id=doc_id,
                source=source,
                title=title,
                snippet=snippet,
                score=score,
                metadata=metadata,
                url=generate_url(source, metadata),
            ))

    return search_results


def search_all(
    query: str,
    sources: Optional[list[str]] = None,
    n_results: int = 10,
) -> list[SearchResult]:
    """Search across multiple collections."""
    if sources is None:
        sources = list(COLLECTIONS.keys())

    sources = [s for s in sources if s in COLLECTIONS]

    all_results = []
    per_collection = max(5, n_results // len(sources) + 2) if sources else 0

    for source in sources:
        collection_name = COLLECTIONS[source]
        try:
            results = search_collection(query, collection_name, n_results=per_collection)
            all_results.extend(results)
        except Exception as e:
            print(f"Warning: Could not search {source}: {e}")
            continue

    # Sort by score descending
    all_results.sort(key=lambda r: r.score, reverse=True)

    # Deduplicate chunked documents
    seen_docs = set()
    deduplicated = []
    for result in all_results:
        # Extract base document ID (remove chunk suffix)
        base_id = result.id.split("_chunk")[0]
        if base_id in seen_docs:
            continue
        seen_docs.add(base_id)
        deduplicated.append(result)

    # Rerank results using cross-encoder for better relevance
    if len(deduplicated) > 1:
        deduplicated = rerank_results(query, deduplicated, n_results)

    return deduplicated[:n_results]


def search_with_filters(
    query: str,
    sources: Optional[list[str]] = None,
    n_results: int = 10,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[SearchResult]:
    """Search with optional date filtering."""
    results = search_all(query, sources, n_results=n_results * 2)

    # Apply date filtering post-query
    if date_from or date_to:
        filtered = []
        for r in results:
            doc_date = (
                r.metadata.get("grant_date") or
                r.metadata.get("award_date") or
                r.metadata.get("date", "")
            )
            if not doc_date:
                filtered.append(r)
                continue
            if date_from and doc_date < date_from:
                continue
            if date_to and doc_date > date_to:
                continue
            filtered.append(r)
        results = filtered

    return results[:n_results]
