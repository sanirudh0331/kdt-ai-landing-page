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
| Typing Effect | ✅ Done | Word-by-word response animation with cursor |
| Voice Input | ✅ Done | Web Speech API microphone button for speech-to-text |

### Files Changed
- `index.html` - Chat UI, CSS, JavaScript for conversation management
- `rag/server.py` - Added `messages` and `skip_search` params to AskRequest
- `rag/llm.py` - Updated `ask_with_context()` to include conversation history

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
