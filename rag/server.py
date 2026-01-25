"""FastAPI server for RAG search endpoints."""

import os
import sys
from typing import Optional

# Support both module run (python -m rag.server) and standalone (uvicorn server:app)
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from fastapi import FastAPI, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class AskRequest(BaseModel):
    """Request body for the ask endpoint."""
    question: str
    n_context: int = 5


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
        try:
            from search import search_with_filters
        except ImportError:
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


@app.post("/api/rag-ask")
async def rag_ask(request: AskRequest):
    """AI-powered Q&A using RAG context."""
    import os

    # Check if disabled
    if os.environ.get("DISABLE_ASK", "").lower() == "true":
        return JSONResponse(
            status_code=503,
            content={"error": "AI Q&A is temporarily disabled"}
        )

    try:
        # Import search and LLM modules
        try:
            from search import search_with_filters
            from llm import ask_with_context
        except ImportError:
            from rag.search import search_with_filters
            from rag.llm import ask_with_context

        # First, search for relevant context
        context_results = search_with_filters(
            query=request.question,
            sources=None,  # Search all sources
            n_results=request.n_context,
        )

        # Convert search results to dicts for the LLM
        context_docs = []
        for r in context_results:
            doc = r.to_dict()
            context_docs.append(doc)

        # Get AI answer
        result = ask_with_context(
            question=request.question,
            context_docs=context_docs,
        )

        return {
            "question": request.question,
            "answer": result["answer"],
            "sources": result["sources"],
            "context_count": result["context_count"],
            "model": result.get("model"),
        }

    except ImportError as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": "RAG Q&A not available",
                "detail": str(e),
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "Q&A failed", "detail": str(e)}
        )


@app.get("/api/rag-stats")
async def rag_stats():
    """Get statistics about indexed data."""
    try:
        try:
            from ingest import get_collection_stats
        except ImportError:
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


@app.post("/api/rag-ingest")
async def rag_ingest(
    secret: str = Query(..., description="Ingest secret key"),
    reset: bool = Query(False, description="Reset all collections before ingesting"),
    resume: bool = Query(False, description="Resume from last checkpoint"),
):
    """Trigger data ingestion (protected endpoint)."""
    import os
    expected_secret = os.environ.get("INGEST_SECRET", "")

    if not expected_secret or secret != expected_secret:
        return JSONResponse(status_code=403, content={"error": "Invalid secret"})

    try:
        try:
            from ingest import ingest_all, get_collection_stats, load_checkpoint
        except ImportError:
            from rag.ingest import ingest_all, get_collection_stats, load_checkpoint

        # If resume requested, get checkpoint info
        checkpoint_info = None
        if resume:
            checkpoint_info = load_checkpoint()

        results = ingest_all(reset=reset, verbose=False)
        stats = get_collection_stats()
        return {
            "status": "complete",
            "indexed": results,
            "collections": stats,
            "resumed_from": checkpoint_info if resume else None
        }
    except ImportError as e:
        return JSONResponse(
            status_code=503,
            content={"error": "RAG not available", "detail": str(e)}
        )
    except Exception as e:
        # On error, include checkpoint info
        try:
            try:
                from ingest import load_checkpoint, get_collection_stats
            except ImportError:
                from rag.ingest import load_checkpoint, get_collection_stats
            checkpoint = load_checkpoint()
            stats = get_collection_stats()
            return JSONResponse(
                status_code=500,
                content={
                    "error": str(e),
                    "checkpoint": checkpoint,
                    "collections": stats,
                    "hint": "Use resume=true to continue from checkpoint"
                }
            )
        except Exception:
            return JSONResponse(
                status_code=500,
                content={"error": str(e)}
            )


@app.get("/api/rag-checkpoint")
async def rag_checkpoint():
    """Get current ingestion checkpoint status."""
    try:
        try:
            from ingest import load_checkpoint
        except ImportError:
            from rag.ingest import load_checkpoint
        return {"checkpoint": load_checkpoint()}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("RAG_PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
