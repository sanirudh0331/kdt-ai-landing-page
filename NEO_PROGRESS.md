# Neo MCP - Progress Notes

**Last Updated:** 2026-01-31

---

## How Neo Search & Querying Works

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER QUESTION                                   │
│                    "Who are the rising stars in oncology?"                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LANDING PAGE (Node.js)                             │
│                        https://kdt-ai.railway.app                            │
│  • Chat UI with conversation history                                         │
│  • Proxies requests to Neo MCP service                                       │
│  • Handles SSE streaming for real-time updates                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                           POST /api/neo-analyze
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         NEO MCP SERVICE (Python)                             │
│                       https://kdtneo.up.railway.app                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ STEP 1: QUESTION ROUTER (router.py)                                  │   │
│  │                                                                       │   │
│  │ Classifies question into 3 tiers:                                    │   │
│  │                                                                       │   │
│  │ TIER 1 - Instant (no LLM)      "How many trials?"                    │   │
│  │   └─→ Direct SQL patterns       └─→ SELECT COUNT(*) → 89,018         │   │
│  │                                                                       │   │
│  │ TIER 2 - Fast (no LLM)         "Trials for cancer"                   │   │
│  │   └─→ Parameterized templates   └─→ SELECT ... WHERE conditions      │   │
│  │                                      LIKE '%cancer%'                  │   │
│  │                                                                       │   │
│  │ TIER 3 - Full Agent (Claude)   "Compare patent landscapes for        │   │
│  │   └─→ Complex/cross-DB queries   our oncology portfolio companies"   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                       │                                      │
│               ┌───────────────────────┴───────────────────────┐             │
│               │                                               │             │
│               ▼ (if Tier 3)                                   ▼ (Tier 1/2)  │
│  ┌────────────────────────────────┐              ┌─────────────────────┐    │
│  │ STEP 2: SEMANTIC CACHE         │              │ Return answer       │    │
│  │ (semantic_cache.py)            │              │ immediately         │    │
│  │                                │              │ No LLM cost!        │    │
│  │ • SQLite + embeddings          │              └─────────────────────┘    │
│  │ • 80% similarity threshold     │                                         │
│  │ • 1-hour TTL                   │                                         │
│  │                                │                                         │
│  │ Similar question found?        │                                         │
│  │ "Rising stars in immunology"   │                                         │
│  │  → Return cached answer        │                                         │
│  └────────────────────────────────┘                                         │
│               │ (cache miss)                                                 │
│               ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ STEP 3: CLAUDE AGENT LOOP (agent.py)                                 │   │
│  │                                                                       │   │
│  │ Claude Sonnet with tool_use API:                                     │   │
│  │                                                                       │   │
│  │ while not done and turns < 25:                                       │   │
│  │   1. Claude thinks about what to do                                  │   │
│  │   2. Claude calls a tool (query_researchers, query_patents, etc.)    │   │
│  │   3. Tool executes SQL against Railway databases                     │   │
│  │   4. Results returned to Claude                                      │   │
│  │   5. Claude decides: need more info? → loop, else → respond          │   │
│  │                                                                       │   │
│  │ Available tools (tools.py):                                          │   │
│  │   • query_researchers  - 242K researchers                            │   │
│  │   • query_patents      - 2.4K patents                                │   │
│  │   • query_grants       - 392K grants ($222B)                         │   │
│  │   • query_policies     - 28 bills                                    │   │
│  │   • query_portfolio    - 24 companies                                │   │
│  │   • query_market_data  - 89K clinical trials                         │   │
│  │   • list_tables        - Discover schema                             │   │
│  │   • describe_table     - Get column info                             │   │
│  │   • append_insight     - Record findings                             │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│               │                                                              │
│               ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ STEP 4: DATABASE LAYER (db.py)                                       │   │
│  │                                                                       │   │
│  │ Each tool call → HTTP POST to Railway service → SQL execution        │   │
│  │                                                                       │   │
│  │ • 5-minute query cache (avoid repeated identical queries)            │   │
│  │ • Auto-add LIMIT if missing (safety)                                 │   │
│  │ • Retry logic with longer timeouts                                   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                    HTTP POST /api/sql to each Railway service
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         RAILWAY DATABASE SERVICES                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │  Talent Scout   │  │ Patent Warrior  │  │ Grants Tracker  │              │
│  │  (researchers)  │  │   (patents)     │  │    (grants)     │              │
│  │  242K records   │  │   2.4K records  │  │  392K records   │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │  Policy Watch   │  │   Portfolio     │  │  Clinical Trials │             │
│  │   (policies)    │  │  (companies)    │  │  (market_data)   │             │
│  │   28 records    │  │   24 records    │  │  89K records     │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Request Flow Example

**Question:** "Find rising star researchers in oncology who might be relevant for our Epana portfolio"

```
1. USER SUBMITS QUESTION
   └─→ POST /api/neo-analyze { question: "Find rising star researchers..." }

2. ROUTER CHECK (router.py)
   └─→ Cross-DB detected (researchers + portfolio)
   └─→ Tier 3: Needs full agent

3. SEMANTIC CACHE CHECK (semantic_cache.py)
   └─→ No similar question found (< 80% similarity)
   └─→ Cache miss

4. CLAUDE AGENT LOOP (agent.py)

   Turn 1:
   └─→ Claude thinks: "I need to understand Epana first"
   └─→ Tool call: query_portfolio
       { "query": "SELECT * FROM companies WHERE name LIKE '%Epana%'" }
   └─→ Result: { modality: "T-cell Engager", indications: "CD38/CD19, autoimmune" }

   Turn 2:
   └─→ Claude thinks: "Now find researchers in relevant areas"
   └─→ Tool call: query_researchers
       { "query": "SELECT id, name, h_index, slope FROM researchers
                   WHERE (topics LIKE '%T-cell%' OR topics LIKE '%autoimmune%')
                   AND slope > 3 AND h_index BETWEEN 20 AND 60
                   ORDER BY slope DESC LIMIT 15" }
   └─→ Result: [{ name: "Dr. Smith", h_index: 45, slope: 5.2 }, ...]

   Turn 3:
   └─→ Claude thinks: "I have enough info to respond"
   └─→ Returns formatted answer with recommendations

5. CACHE RESPONSE
   └─→ Store answer + embedding for future similar questions

6. RETURN TO USER
   └─→ { answer: "...", entities: [...], tool_calls: [...], turns_used: 3 }
```

### Cost Optimization Layers

| Layer | What it does | Cost |
|-------|--------------|------|
| **Tier 1 Router** | Instant SQL for counts/stats | $0 |
| **Tier 2 Router** | Parameterized queries | $0 |
| **Semantic Cache** | Reuse similar answers (80% threshold) | $0 |
| **Query Cache** | 5-min cache for identical SQL | $0 |
| **Full Agent** | Claude Sonnet + SQL | ~$0.01-0.05/question |

### Key Files

| File | Purpose |
|------|---------|
| `server.py` | FastAPI endpoints, SSE streaming |
| `router.py` | Tier 1/2/3 question classification |
| `semantic_cache.py` | SQLite + embeddings for similar questions |
| `agent.py` | Claude agentic loop with tool_use |
| `tools.py` | Tool definitions for Claude |
| `db.py` | HTTP calls to Railway services |

### Database Service URLs

| Service | URL | Records |
|---------|-----|---------|
| Researchers | kdttalentscout.up.railway.app | 242,000 |
| Patents | patentwarrior.up.railway.app | 2,400 |
| Grants | grants-tracker-production.up.railway.app | 392,000 |
| Policies | policywatch.up.railway.app | 28 |
| Portfolio | web-production-a9d068.up.railway.app | 24 |
| Clinical Trials | clinicaltrialsdata.up.railway.app | 89,018 |

---

## Router v2: Smart Question Routing (2026-01-28)

### Summary
Major upgrade to question router with 5 new improvements. Reduces API costs and improves response speed for common queries.

### Improvements Implemented

| # | Improvement | Description | Benefit |
|---|-------------|-------------|---------|
| 1 | **Clinical Trials Tier 2 Patterns** | Parameterized queries for trials | Fast responses without LLM |
| 2 | **Cross-Database Patterns** | Detects multi-DB questions | Better routing hints for agent |
| 3 | **Keyword-Based DB Routing** | Maps keywords to databases | Faster DB detection |
| 4 | **Intent Detection** | Regex-based intent classification | No LLM needed for routing |
| 5 | **Cached Aggregations** | TTL cache for common agg queries | 5min cache, instant responses |

### New Clinical Trials Tier 2 Patterns

These queries now execute instantly (no Claude API call):

| Pattern | Example |
|---------|---------|
| `trials for {condition}` | "Trials for cancer?" |
| `{sponsor}'s trials` | "Pfizer's clinical trials" |
| `recruiting trials for {field}` | "Recruiting trials for diabetes" |
| `phase N trials for {condition}` | "Phase 3 trials for Alzheimer's" |
| `top N sponsors by trials` | "Top 10 sponsors by trial count" |
| `trials started in {year}` | "Trials started in 2024" |

### Keyword-Based Database Detection

Router now maps keywords to databases:

```python
DB_KEYWORDS = {
    "researchers": ["h-index", "citations", "rising star", "hidden gem", ...],
    "patents": ["patent", "assignee", "claims", "filing", ...],
    "grants": ["grant", "funding", "nih", "nsf", "r01", ...],
    "market_data": ["trial", "recruiting", "phase", "sponsor", "fda", ...],
    "portfolio": ["portfolio", "company", "modality", "indication", ...],
    "policies": ["bill", "policy", "legislation", "congress", ...],
}
```

### Intent Detection (Regex-Based)

Detects user intent without LLM:

| Intent | Patterns |
|--------|----------|
| `count` | "how many", "number of", "total count" |
| `list` | "list all", "show me", "what are", "find" |
| `top_n` | "top 5", "best 10", "highest", "most" |
| `compare` | "compare", "vs", "difference between" |
| `lookup` | "what is", "tell me about", "who is" |
| `aggregate` | "total", "sum", "average", "by status" |
| `filter` | "where", "with", "greater than", "over $1M" |
| `cross_db` | "researchers with patents", "grants and trials" |

### Cached Aggregations

Common aggregation queries are cached for 5 minutes:

| Cache Key | Description |
|-----------|-------------|
| `trials_by_status` | Count by RECRUITING, COMPLETED, etc. |
| `trials_by_phase` | Count by Phase 1, 2, 3, 4 |
| `trials_by_sponsor` | Top 20 sponsors |
| `grants_by_institute` | Top 20 institutes by funding |
| `researchers_by_category` | Top 20 research categories |

### Routing Hints for Tier 3

When questions require the full Claude agent, router now provides hints:

```json
{
  "tier": 3,
  "tier_name": "agent",
  "needs_agent": true,
  "routing_hints": {
    "detected_dbs": ["researchers", "patents"],
    "intents": ["list", "cross_db"],
    "hint": "cross_db",
    "suggested_queries": [...]
  }
}
```

### Cost Impact

| Query Type | Before | After |
|------------|--------|-------|
| "How many recruiting trials?" | Claude API call | Instant SQL |
| "Pfizer's trials" | Claude API call | Tier 2 template |
| "Trials by status" | Claude API call | Cached (5min) |
| Complex cross-DB | Claude API call | Claude + hints |

### Files Changed

- `neo_mcp/router.py` - All 5 improvements implemented

---

## Clinical Trials Integration Complete (2026-01-28)

### Summary
Full integration of ClinicalTrials.gov data into Neo. Neo can now answer questions about clinical trials, pipelines, and sponsors.

### Data Synced

| Metric | Count |
|--------|-------|
| **Total Clinical Trials** | 89,018 |
| COMPLETED | 34,806 |
| RECRUITING | 28,505 |
| NOT_YET_RECRUITING | 11,237 |
| ACTIVE_NOT_RECRUITING | 9,798 |
| Other statuses | 2,672 |

### Sync Strategy (Option C)
- **All active trials** - Any status that's still running (no date filter)
- **Completed trials since 2023** - Recent outcomes for pipeline analysis
- **All sponsors** - Not limited to portfolio companies

### Weekly Automated Sync

GitHub Action: `.github/workflows/sync-clinical-trials.yml`
- **Schedule:** Every Sunday 2am UTC
- **Mode:** Incremental (`--incremental --days 7`)
- Only fetches trials updated in last 7 days
- Updates existing trials + adds new ones

### Neo Integration

Added to Neo agent:
- `query_market_data` tool in `tools.py`
- Tool handler in `agent.py`
- `market_data` service URL in `db.py`
- System prompt updated with clinical_trials schema

### Service URLs

| Service | URL |
|---------|-----|
| Clinical Trials API | `https://clinicaltrialsdata.up.railway.app` |
| Neo MCP | `https://kdtneo.up.railway.app` |

### Example Questions Neo Can Answer

- "How many Phase 3 trials are recruiting?"
- "What are the top sponsors by trial count?"
- "Show me oncology trials in Phase 2"
- "What trials has AstraZeneca completed recently?"

### Bug Fix: Railway Watch Path

**Issue:** Railway wasn't auto-deploying from GitHub
**Root Cause:** Watch path was set to `rag/**` (old folder name) instead of `neo_mcp/**`
**Fix:** Updated watch path in Railway service settings

---

## Market Data Service (2026-01-27)

### Summary
Created new Railway service to host FDA calendar and clinical trials data.

### Service: `market_data/`

| File | Description |
|------|-------------|
| `server.py` | FastAPI server with SQL endpoints |
| `sync_data.py` | Sync script with `--incremental` and `--full` modes |
| `Dockerfile` | Python 3.11-slim container |
| `requirements.txt` | FastAPI, uvicorn, httpx |
| `railway.toml` | Railway build configuration |

### Database Tables

**`clinical_trials`** - 89,018 trials from ClinicalTrials.gov
- `nct_id`, `brief_title`, `status`, `phase`, `sponsor`, `conditions`, `interventions`
- `enrollment`, `start_date`, `completion_date`, `locations_count`, `has_results`

**`fda_events`** - FDA calendar / PDUFA dates (not yet synced)
- `event_type`, `ticker`, `company`, `drug`, `indication`, `event_date`, `url`

### Sync Commands

```bash
# Full sync (initial population)
python sync_data.py --full

# Incremental sync (weekly cron)
python sync_data.py --incremental --days 7

# Specific sponsor
python sync_data.py --full --sponsor "Pfizer"
```

---

## Rename: rag → neo_mcp (2026-01-27)

### Summary
Renamed the entire RAG module to Neo MCP to better reflect its current purpose (SQL agent + MCP-style database access rather than vector-based RAG).

### Changes Made

| Change | Old | New |
|--------|-----|-----|
| Folder | `rag/` | `neo_mcp/` |
| Progress file | `RAG_PROGRESS.md` | `NEO_PROGRESS.md` |
| Railway service | `kdtrag` | `kdtneo` (neo_mcp service) |
| Service URL | `https://kdtrag.up.railway.app` | `https://kdtneo.up.railway.app` |
| Env variable | `RAG_SERVICE_URL` | `NEO_SERVICE_URL` |

### API Endpoints Renamed

| Old | New |
|-----|-----|
| `/api/rag-search` | `/api/neo-search` |
| `/api/rag-ask` | `/api/neo-ask` |
| `/api/rag-stats` | `/api/neo-stats` |
| `/api/rag-ingest` | `/api/neo-ingest` |
| `/api/rag-checkpoint` | `/api/neo-checkpoint` |
| `/api/rag-debug` | `/api/neo-debug` |

### Files Updated
- All Python files in `neo_mcp/` - Updated imports from `rag.*` to `neo_mcp.*`
- `server.js` - Updated proxy endpoints and `NEO_SERVICE_URL`
- `index.html` - Updated API endpoint calls
- Documentation files - Updated paths and URLs

### Railway Configuration
- **neo_mcp service**: Root directory set to `neo_mcp`
- **Landing page**: `NEO_SERVICE_URL=https://kdtneo.up.railway.app`

### Commit
- `f6cc50b` - Rename rag/ to neo_mcp/ and update all API endpoints

---

## Neo Agent v2: Streaming, Entity Linking & Smart Routing (2026-01-27)

### Summary
Major overhaul of Neo agent backend: added real-time streaming updates, clickable entity sources, question routing with semantic caching, and various UX improvements.

### Features Implemented

| Feature | Status | Description |
|---------|--------|-------------|
| Streaming Status Updates | ✅ Done | Real-time SSE streaming shows what Neo is doing ("Searching patents...", "Running SQL...") |
| SSE Proxy | ✅ Done | Node.js proxy forwards SSE events from Python backend |
| Question Router | ✅ Done | Routes questions to Tier 1 (RAG) or Tier 2 (SQL agent) based on complexity |
| Semantic Cache | ✅ Done | SQLite-based cache for similar questions (faster, cheaper than ChromaDB) |
| Clickable Entity Sources | ✅ Done | Responses include linked patents/grants/researchers that open in side panel |
| Entity Extraction | ✅ Done | Parses Neo responses to find and link entity references |
| Entity Caching | ✅ Done | Cached responses include their entity links |
| Fullscreen Toggle | ✅ Done | Expand Neo chat modal to full viewport |
| Default Tab Change | ✅ Done | "Ask Neo" is now the default tab instead of Search |

### Architecture Changes

**Question Routing (Tier System):**
- **Tier 1 (RAG):** Simple factual questions → fast vector search + LLM
- **Tier 2 (SQL Agent):** Complex/analytical questions → multi-turn SQL agent with tool use
- Router uses Claude to classify incoming questions

**Semantic Cache:**
- Switched from ChromaDB to SQLite for simplicity
- Stores question embeddings + responses
- Similarity threshold determines cache hits
- Reduces API costs for repeated/similar questions

**Streaming Implementation:**
- Python backend streams SSE events with status updates
- Node.js server proxies `/api/neo-stream` to Python service
- Frontend shows real-time progress indicators

### Files Changed
- `server.js` - Added SSE proxy endpoint `/api/neo-stream`
- `neo_mcp/server.py` - Streaming endpoint, question router, entity extraction
- `neo_mcp/semantic_cache.py` - SQLite semantic cache implementation
- `index.html` - Streaming UI, entity linking, fullscreen, default tab

### Commits
- `28c6520` - Add Neo SQL agent proxy endpoint to Node.js server
- `1a5958b` - Point to deployed kdtrag service for Neo SQL agent
- `78f3d1f` - Optimize Neo agent: add schemas to prompt, increase max turns to 25
- `959e9d4` - Switch Neo to direct Railway SQL calls (like MCP)
- `ed2f670` - Increase SQL query timeout to 90s for large tables
- `b9894b9` - Improve Neo agent reliability for production
- `918b7ed` - Add question router and semantic cache for Neo agent
- `66b1046` - Simplify semantic cache: SQLite instead of ChromaDB
- `1eab6ae` - Improve Neo chat UI and add source references
- `f2d2dd6` - Add clickable entity sources to Neo responses
- `8078ebc` - Fix: Return entities from /api/neo-analyze endpoint
- `c0023c6` - Add entity extraction for Tier 2 routed queries
- `f4ad707` - Add entity caching for cached responses
- `a70b360` - Add empty entities array to Tier 1 responses for consistency
- `b88405a` - Fix: Add id column to Tier 2 queries for entity linking
- `65635f4` - Add automatic entity linking in Neo responses
- `330c9e7` - Add fullscreen toggle for Neo chat modal
- `419891f` - Make Ask Neo the default tab instead of Search
- `a67fb5f` - Add real-time streaming status updates for Neo
- `d392f4c` - Add streaming proxy for Neo SSE endpoint

### Bug Fixes
- Entity linking required `id` column in Tier 2 SQL queries
- Empty entities array needed for Tier 1 responses (frontend consistency)
- Cached responses weren't returning entity data

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
| Typing Effect | ✅ Done | Word-by-word response animation with cursor |
| Voice Input | ✅ Done | Web Speech API microphone button for speech-to-text |

### Files Changed
- `index.html` - Chat UI, CSS, JavaScript for conversation management
- `neo_mcp/server.py` - Added `messages` and `skip_search` params to AskRequest
- `neo_mcp/llm.py` - Updated `ask_with_context()` to include conversation history

### Cost Optimization
- Follow-up questions skip RAG search (reuse existing context)
- Topic changes clear history (shorter context = fewer tokens)
- All detection logic is client-side (no API calls)

### Voice Input Implementation
Uses the Web Speech API (`SpeechRecognition`/`webkitSpeechRecognition`):
- **Browser Support:** Chrome, Edge, Safari (partial). Not supported in Firefox.
- **Features:** Interim results show as you speak, auto-stops on silence
- **Error Handling:** Alerts user if microphone access denied or browser unsupported
- **UI Feedback:** Button turns red and pulses while recording

### Commits
- `c44a6ec` - Add Neo chat interface with conversation history and smart topic detection
- `82b6cc3` - Fix stale DOM reference for chatWelcome element
- `9bcaf6d` - Fix: check isFollowUp before adding question to history
- `82426b3` - UX improvements (short query fix, Enter key, clear confirmation)
- `244ad3c` - Chat animations (slide-in, shadows, glow pulse)
- `8487283` - Pulsating logo + fun thinking messages
- `1604914` - Remove background watermark for cleaner look
- `e269fd7` - Custom themed scrollbar for chat and search panels
- `75530ae` - Copy button, keyboard shortcut, timestamps, source chips, auto-links, expand/collapse
- `ad176d8` - Typing effect, voice input, suggested questions, mobile improvements
- `0ceaf59` - Collapsible sources section (minimizes on new question)
- `612b50c` - Remove suggested questions feature
- `2b46717` - Keep long messages expanded until next question
- `38809b2` - Improve Neo response text formatting and typography
- `f2c8063` - Improve user message styling (line-height, auto-link URLs)
- `a2e9fc2` - Better list spacing, clickable reference links [1], [2]
- `139e779` - Fix user message spacing
- `a0de787` - CSS counters for numbered list continuity (fixes 1, 1 -> 1, 2)
- `b50a3eb` - Inline timestamp for compact user messages
- `19dc964` - Fix user bubble alignment (width: fit-content)
- `aa2107d` - Update progress notes
- `[new]` - Offline banner and scroll-to-bottom button

### UX & Visual Polish (2026-01-26)

| Improvement | Description |
|-------------|-------------|
| Short query fix | Require at least one full exchange before short-query follow-up detection |
| Enter key support | Submit chat messages with Enter key |
| Clear confirmation | Confirm before clearing conversation history |
| Slide-in animation | Chat bubbles animate in smoothly |
| Subtle shadows | Depth added to message bubbles |
| Glow pulse | Neo bubble glows while thinking |
| Thinking indicator | Pulsating logo + random fun messages ("Searching...", "Connecting the dots...") |
| Clean design | Removed background watermark |
| Custom scrollbar | Thin, themed indigo scrollbar for chat & search panels |
| Copy button | Click to copy Neo's responses with checkmark feedback |
| Keyboard shortcut | `Cmd/Ctrl+K` to focus search input from anywhere |
| Message timestamps | Show time (HH:MM) on each message |
| Source chips | Improved styling with hover effects and source type labels |
| Auto-link URLs | URLs in responses are automatically clickable |
| Expand/collapse | Long messages (800+ chars) show "Show more/less" button |
| Typing effect | Responses appear word-by-word with blinking cursor animation |
| Voice input | Microphone button uses Web Speech API for voice-to-text |
| Mobile improvements | Larger touch targets, iOS zoom prevention (16px inputs) |
| Collapsible sources | Sources expand after response, collapse on new question |
| Neo text formatting | Proper lists, paragraphs, code blocks, bold/italic |
| Reference links | [1], [2] in responses link to actual sources |
| User message compact | Inline timestamp, fit-content width, right-aligned |
| List numbering | CSS counters maintain 1, 2, 3 across bullet interruptions |
| Offline banner | Yellow warning bar when connection lost |
| Scroll to bottom | Centered floating button when scrolled up in chat |

### Bug Fixes (2026-01-26)

**Issue:** First question returned "I don't have any relevant documents" error

**Root Cause:**
- `isFollowUp()` was checked AFTER adding the question to conversation history
- This caused `conversationHistory.length > 0` even for first questions
- Short queries (≤4 words) were incorrectly flagged as follow-ups
- `skip_search=true` was sent, causing RAG search to be skipped

**Fix:** Move `isFollowUp()` check BEFORE adding question to history

**Also Fixed:** Stale DOM reference for `chatWelcome` element after `clearConversation()` replaced innerHTML

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

---

## 2026-01-31: Neo Widget Improvements

### Changes Made

**Widget Design Updates (all KdT tools):**
- Neo button: 56px with gradient background (`#18181b` → `#27272a`)
- Logo: 32px KdT logo with rounded corners
- Indigo glow shadow: `box-shadow: 0 4px 16px rgba(99,102,241,0.4)`
- Modal: 800px width, 85vh height (up from 600px/80vh)

**New Features:**
- Model selector (Sonnet/Opus/Haiku) in chat modal header
- Session persistence via localStorage + server API
- Mobile responsive CSS (media queries for < 640px)

**Session Persistence API (server.js):**
- `GET /api/conversation/:sessionId` - Retrieve conversation history
- `POST /api/conversation/:sessionId` - Save conversation history
- `DELETE /api/conversation/:sessionId` - Clear conversation
- In-memory storage with 24-hour expiry

**Updated Repos:**
- ✅ KdT Landing Page (`index.html`, `server.js`, `floating-widget-snippet.html`)
- ✅ Patent Warrior (all templates)
- ✅ H-Index Tracker (dashboard, compare, researcher, rising_stars)
- ✅ Grants Tracker (`base.html` - Jinja inheritance)
- ✅ Policy Watch (`base.html` - Jinja inheritance)
- ✅ SEC Sentinel (all 6 templates: dashboard, holdings, insider, ipos, runway, talent)

**Documentation:**
- Added detailed header comment to `floating-widget-snippet.html`
- Documents how to copy widget to new tools with Railway links

**Note:** All Railway-linked tools on the KdT landing page now have the Neo widget integrated.

### 2026-01-31 Update: Widget Redesign (Match Home Page Style)

Updated Neo widget across all tools to match the home page design:

**Header Changes:**
- "Clear chat" button moved to the LEFT with trash icon
- "Model:" label + dropdown on the RIGHT (styled as purple button)
- Model dropdown: purple (#6366f1) background, white text, dropdown arrow

**Welcome Screen:**
- Larger logo (64px vs 48px)
- "KdT Neo" title with muted gray styling
- Updated tagline: "Ask Neo anything about KdT's knowledge base"

**Input Area:**
- Placeholder: "Continue the conversation..."
- Added microphone button (for future voice input)
- Send button with arrow icon

**Footer:**
- "Press Esc to close" on LEFT
- "Powered by Claude" link on RIGHT

**Repos Updated:**
- ✅ Portfolio Tracker (`base.html`)
- ✅ Policy Tracker (`base.html`)
- ✅ SEC Sentinel (all 6 templates)
- ✅ neo-widget-template.html (master template)

---

## 2026-01-31: About Page Launch

### Summary
Created comprehensive About page for KdT AI landing site with tool documentation, FAQ, changelog, and keyboard shortcuts.

### New Page: `/about.html`

**Navigation:**
- "KdT AI Home" button (matches other tools' back navigation)
- Theme toggle preserved
- About link moved before Tools in landing page nav

**Sections Added:**

| Section | Content |
|---------|---------|
| **Header** | Updated description for KdT team focus |
| **KdT Neo** | What Neo can do, tips for better results |
| **Tools Guide** | All 8 tools with descriptions and key features |
| **Data Sources** | Research/Academia + Clinical/Regulatory sources |
| **Keyboard Shortcuts** | Home page (/, 1-9, T) and Neo chat (Esc, Enter) |
| **FAQ** | 9 questions covering data updates, exports, Neo models, and upcoming features |
| **Recent Updates** | Changelog grouped by month (Jan 2026, Dec 2025, Nov 2025) |
| **Feedback** | Pointer to feedback button |

**Tools Documented:**
1. Portfolio Beacon - portfolio company tracking
2. Talent Scout - researcher h-index tracking (242K+ researchers)
3. Conference Navigator - conference planning
4. Deal Watchdog - biotech deals monitoring
5. Grant Radar - NIH grants (392K+ grants)
6. SEC Sentinel - SEC filings, 13F, insider trading
7. Patent Warrior (In Development) - IP tracking
8. Policy Watch (In Development) - legislation tracking

**FAQ Topics:**
- Data update frequency
- CSV export availability
- Neo model options (Sonnet/Opus/Haiku)
- Cross-database search capability
- Upcoming: watchlists, mobile app, alerts, team sharing

**Changelog Based on Git History:**
- Pulled actual commits from last 30 days across all KdT repos
- Organized by month with tool-specific updates

**Neo Widget:**
- Full widget + feedback button added to About page
- Theme-aware styling (light/dark mode)
- All functionality matches other tools

### Files Changed
- `about.html` - New comprehensive About page
- `index.html` - Moved About link before Tools in nav

### Commit
- `d54e614` - Enhance About page with Neo widget, FAQ, changelog, and keyboard shortcuts
