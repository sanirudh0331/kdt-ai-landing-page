# RAG Embedding Quality Improvement - Progress Notes

**Last Updated:** 2026-01-26

---

## Neo Chat Interface (2026-01-26)

### Summary
Converted Neo from single Q&A to a full chat interface with conversation history and smart topic detection.

### Features Implemented

| Feature | Status | Description |
|---------|--------|-------------|
| Chat UI | ✅ Done | Message bubbles, typing indicator, scrollable history |
| Conversation History | ✅ Done | Backend accepts messages array, includes in Claude context |
| localStorage Persistence | ✅ Done | 14-day expiry, auto-loads on page refresh |
| Smart Follow-up Detection | ✅ Done | Skips RAG search for follow-ups (cost savings) |
| Topic Detection | ✅ Done | Auto-clears conversation when topic changes |
| Chat Input Field | ✅ Done | Continue conversation without using search bar |
| Enlarged Modal | ✅ Done | 90% viewport height, responsive width |

### Files Changed
- `index.html` - Chat UI, CSS, JavaScript for conversation management
- `rag/server.py` - Added `messages` and `skip_search` params to AskRequest
- `rag/llm.py` - Updated `ask_with_context()` to include conversation history

### Cost Optimization
- Follow-up questions skip RAG search (reuse existing context)
- Topic changes clear history (shorter context = fewer tokens)
- All detection logic is client-side (no API calls)

### Commit
- `c44a6ec` - Add Neo chat interface with conversation history and smart topic detection

---

## Previous Progress (2026-01-25)

---

## Summary

Attempted to implement RAG quality improvements. Partial success - some features working, others deferred.

---

## What Was Implemented

### Phase 1: Cross-Encoder Reranking
- **Status:** Code added, but DISABLED
- **Reason:** Model download on first request caused timeouts
- **Files changed:** `rag/search.py`
- **TODO:** Pre-load reranker model on server startup, then re-enable

### Phase 2: Embedding Model Upgrade
- **Status:** REVERTED
- **Reason:** BGE model (768 dims, ~440MB) too heavy for Railway - caused server to hang during ingest
- **Current model:** `all-MiniLM-L6-v2` (384 dims) - original lightweight model

### Phase 2: Improved Chunking
- **Status:** WORKING
- **Changes:**
  - Chunk size reduced from 2000 to 1500 chars
  - Added 200 char overlap between chunks
  - Added position tracking (`chunk_index`, `total_chunks` in metadata)
- **Files changed:** `rag/ingest.py`

### Phase 3: Researchers (Talent Scout)
- **Status:** Code added, NOT YET INGESTED
- **URL configured:** `https://kdttalentscout.up.railway.app`
- **Files changed:** `rag/ingest.py`
- **TODO:** Run incremental ingest for researchers

---

## Current State

```
Collection    | Count  | Status
--------------|--------|------------------
Patents       | 2,941  | ✅ Indexed (384 dims)
Grants        | 2,700  | ✅ Indexed (384 dims)
Researchers   | 0      | ❌ Not ingested
Policies      | 0      | ❌ Not ingested
FDA Calendar  | 0      | ❌ Not ingested
```

**Service Status:** WORKING
- Search: ✅ Working
- Ask Neo: ✅ Working (after disabling reranking)
- Reranking: ❌ Disabled

---

## Commits Made

1. `bc277ba` - Improve RAG search quality with reranking and better embeddings
2. `39d7609` - Add researchers ingestion from Talent Scout service
3. `b30ade2` - Revert to lightweight embedding model (BGE too heavy for Railway)
4. `cf68cdf` - Disable reranking temporarily to fix timeout issues

---

## TODO / Next Steps

1. **Pre-load reranker on startup** - Add model initialization to server startup, then re-enable reranking
2. **Ingest remaining sources** (without reset):
   - Researchers from Talent Scout
   - Policies from PolicyWatch
   - FDA Calendar from local JSON
3. **Consider async ingestion** - Current sync ingest blocks entire server
4. **Evaluate smaller reranker models** - `cross-encoder/ms-marco-MiniLM-L-6-v2` may still be too slow

---

## Lessons Learned

- BGE embedding model too heavy for Railway free/hobby tier
- Cross-encoder reranking adds significant latency, needs pre-loading
- Full re-ingest with reset is risky - blocks server for extended periods
- Incremental ingests (without reset) are safer
