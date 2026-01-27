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
    model: str = "claude-3-5-haiku-20241022"
    messages: list = []  # Conversation history for chat mode
    skip_search: bool = False  # Skip RAG search for follow-up questions


class NeoAnalyzeRequest(BaseModel):
    """Request body for the Neo SQL agent endpoint."""
    question: str
    model: str = "claude-sonnet-4-20250514"  # Sonnet for quality analysis
    max_turns: int = 15  # Maximum tool use iterations
    messages: list = []  # Conversation history for follow-ups


app = FastAPI(
    title="KdT AI RAG Search",
    description="Semantic search across all KdT AI tools",
    version="1.0.0"
)


@app.on_event("startup")
async def startup_event():
    """Log startup - Neo now calls Railway services directly (no local DB sync needed)."""
    print("Neo SQL agent ready - queries route directly to Railway services")

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

        # Skip search for follow-up questions that use existing context
        context_docs = []
        if not request.skip_search:
            # Search for relevant context
            context_results = search_with_filters(
                query=request.question,
                sources=None,  # Search all sources
                n_results=request.n_context,
            )

            # Convert search results to dicts for the LLM
            for r in context_results:
                doc = r.to_dict()
                context_docs.append(doc)

        # Get AI answer (with conversation history if provided)
        result = ask_with_context(
            question=request.question,
            context_docs=context_docs,
            model=request.model,
            messages=request.messages,
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
    source: str = Query(None, description="Single source to ingest (patents, grants, researchers, policies, fda_calendar, portfolio). If not specified, ingests all."),
    reset: bool = Query(False, description="Reset all collections before ingesting"),
    resume: bool = Query(False, description="Resume from last checkpoint"),
    limit: int = Query(None, description="Max number of NEW documents to index (for batched ingestion, e.g. limit=2000)"),
):
    """Trigger data ingestion (protected endpoint). Use source param to ingest one collection at a time to avoid timeouts. Use limit for batched ingestion."""
    import os
    expected_secret = os.environ.get("INGEST_SECRET", "")

    if not expected_secret or secret != expected_secret:
        return JSONResponse(status_code=403, content={"error": "Invalid secret"})

    try:
        try:
            from ingest import (ingest_all, get_collection_stats, load_checkpoint,
                               ingest_patents, ingest_grants, ingest_researchers,
                               ingest_policies, ingest_fda_calendar, ingest_portfolio)
        except ImportError:
            from rag.ingest import (ingest_all, get_collection_stats, load_checkpoint,
                                    ingest_patents, ingest_grants, ingest_researchers,
                                    ingest_policies, ingest_fda_calendar, ingest_portfolio)

        # If resume requested, get checkpoint info
        checkpoint_info = None
        if resume:
            checkpoint_info = load_checkpoint()

        # If source specified, only ingest that source
        if source:
            source_funcs = {
                "patents": ingest_patents,
                "grants": ingest_grants,
                "researchers": ingest_researchers,
                "policies": ingest_policies,
                "fda_calendar": ingest_fda_calendar,
                "portfolio": ingest_portfolio,
            }
            if source not in source_funcs:
                return JSONResponse(status_code=400, content={"error": f"Unknown source: {source}. Valid: {list(source_funcs.keys())}"})

            # Pass limit to sources that support it
            if source in ("researchers", "patents", "grants") and limit:
                count = source_funcs[source](reset=reset, verbose=False, limit=limit)
            else:
                count = source_funcs[source](reset=reset, verbose=False)
            results = {source: count}
        else:
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


@app.get("/api/rag-debug")
async def rag_debug():
    """Debug endpoint to check if embeddings are stored correctly."""
    try:
        try:
            from embeddings import get_collection, COLLECTIONS
        except ImportError:
            from rag.embeddings import get_collection, COLLECTIONS

        debug_info = {}
        for source, name in COLLECTIONS.items():
            try:
                collection = get_collection(name)
                count = collection.count()

                if count > 0:
                    # Get one document with embeddings to verify they exist
                    sample = collection.get(
                        limit=1,
                        include=["embeddings", "documents", "metadatas"]
                    )

                    has_embeddings = (
                        sample.get("embeddings") is not None
                        and len(sample["embeddings"]) > 0
                        and sample["embeddings"][0] is not None
                    )

                    embedding_dim = None
                    if has_embeddings:
                        embedding_dim = len(sample["embeddings"][0])

                    debug_info[source] = {
                        "count": count,
                        "has_embeddings": has_embeddings,
                        "embedding_dimensions": embedding_dim,
                        "sample_id": sample["ids"][0] if sample["ids"] else None,
                    }
                else:
                    debug_info[source] = {"count": 0, "has_embeddings": False}

            except Exception as e:
                debug_info[source] = {"error": str(e)}

        return {"status": "ok", "collections": debug_info}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ============ NEO SQL AGENT ENDPOINTS ============
# These replicate MCP functionality - direct SQL access with agentic reasoning

@app.post("/api/neo-analyze")
async def neo_analyze(request: NeoAnalyzeRequest):
    """
    Neo SQL Agent - Direct database access with agentic reasoning.

    This replicates the MCP experience:
    - Claude has direct SQL access to all databases
    - Multi-step reasoning (query -> analyze -> query again)
    - Uses Sonnet/Opus for high-quality analysis
    """
    try:
        try:
            from agent import run_agent
        except ImportError:
            from rag.agent import run_agent

        result = run_agent(
            question=request.question,
            model=request.model,
            max_turns=request.max_turns,
            conversation_history=request.messages if request.messages else None,
        )

        return {
            "question": request.question,
            "answer": result["answer"],
            "tool_calls": result.get("tool_calls", []),
            "insights": result.get("insights", []),
            "model": result.get("model"),
            "turns_used": result.get("turns_used", 0),
            "warning": result.get("warning"),
            "error": result.get("error"),
        }

    except ImportError as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": "Neo SQL agent not available",
                "detail": str(e),
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "Analysis failed", "detail": str(e)}
        )


@app.get("/api/neo-db-stats")
async def neo_db_stats():
    """Get statistics about available SQL databases."""
    try:
        try:
            from db import get_database_stats
        except ImportError:
            from rag.db import get_database_stats

        return {"databases": get_database_stats()}

    except ImportError as e:
        return JSONResponse(
            status_code=503,
            content={"error": "Database module not available", "detail": str(e)}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/neo-query")
async def neo_query(
    database: str = Query(..., description="Database to query (researchers, patents, grants, policies, portfolio)"),
    query: str = Query(..., description="SQL SELECT query"),
):
    """Direct SQL query endpoint (for testing/debugging)."""
    try:
        try:
            from db import execute_query
        except ImportError:
            from rag.db import execute_query

        result = execute_query(database, query)
        return result

    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"error": str(e)}
        )
    except FileNotFoundError as e:
        return JSONResponse(
            status_code=404,
            content={"error": str(e)}
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
