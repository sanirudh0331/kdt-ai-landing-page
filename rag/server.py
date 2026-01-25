"""FastAPI server for RAG search endpoints."""

import os
import sys
from typing import Optional

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(
    title="KdT AI RAG Search",
    description="Semantic search across all KdT AI tools",
    version="1.0.0"
)

# CORS for landing page
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok", "service": "KdT AI RAG Search"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/rag-search")
async def rag_search(
    q: str = Query(..., min_length=1, description="Search query"),
    sources: str = Query("", description="Comma-separated source filters"),
    n_results: int = Query(10, ge=1, le=50, description="Number of results"),
    date_from: str = Query("", description="Filter by date (YYYY-MM-DD)"),
    date_to: str = Query("", description="Filter by date (YYYY-MM-DD)"),
):
    """Semantic search across all KdT AI data sources."""
    try:
        from rag.search import search_with_filters

        source_list = None
        if sources:
            source_list = [s.strip() for s in sources.split(",") if s.strip()]

        results = search_with_filters(
            query=q,
            sources=source_list,
            n_results=n_results,
            date_from=date_from if date_from else None,
            date_to=date_to if date_to else None,
        )

        return {
            "query": q,
            "results": [r.to_dict() for r in results],
            "count": len(results),
            "sources_searched": source_list or ["patents", "grants", "researchers", "policies", "fda_calendar"],
        }

    except ImportError as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": "RAG search not available",
                "detail": str(e),
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "Search failed", "detail": str(e)}
        )


@app.get("/api/rag-stats")
async def rag_stats():
    """Get statistics about indexed data."""
    try:
        from rag.ingest import get_collection_stats
        return {"collections": get_collection_stats()}
    except ImportError as e:
        return JSONResponse(
            status_code=503,
            content={"error": "RAG not available", "detail": str(e)}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("RAG_PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
