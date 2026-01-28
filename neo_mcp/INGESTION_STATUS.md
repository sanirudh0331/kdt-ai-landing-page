# Neo MCP Status

Last updated: 2026-01-28

## Semantic Layer (2026-01-28)

### Completed
- [x] **18 semantic functions** added (4 each for researchers, patents, grants, SEC + 2 cross-DB)
- [x] **_schema_docs tables** in all 4 databases with business context, key column descriptions, and example questions
- [x] **entity_links table** with 35 entities (20 biotech companies, 11 universities, 3 research institutes, 1 gov) for cross-DB resolution
- [x] **Updated system prompt** with synthesis guidelines and tool priority
- [x] **SEC Sentinel integration** with 4 semantic endpoints (filings, runway, insider, alerts)
- [x] **Result caching** (5-min TTL) on all semantic functions

### Semantic Functions Available
| Category | Functions |
|----------|-----------|
| Researchers | `get_researchers`, `get_researcher_profile`, `get_rising_stars`, `get_researchers_by_topic` |
| Patents | `get_patents`, `get_patent_portfolio`, `get_inventors_by_company`, `search_patents_by_topic` |
| Grants | `get_grants`, `get_funding_summary`, `get_pis_by_organization`, `get_grants_by_topic` |
| SEC Sentinel | `get_sec_filings`, `get_companies_by_runway`, `get_insider_transactions`, `get_runway_alerts` |
| Cross-DB | `search_entity`, `get_company_profile` |

### Files Modified
- `neo_mcp/tools.py` (213 → 659 lines) - 18 semantic function tool definitions
- `neo_mcp/db.py` (219 → 801 lines) - Semantic function implementations + SEC client
- `neo_mcp/agent.py` (698 → 870 lines) - Updated system prompt, execute_tool routing, status messages
- `sec-sentinel/app.py` (692 → 942 lines) - 4 semantic API endpoints

### Remaining
- [ ] Deploy updated Neo to Railway
- [ ] Deploy updated SEC Sentinel to Railway
- [ ] Test 20 key questions end-to-end
- [ ] Populate Form 4 transaction data (SEC Sentinel)
- [ ] Add more entities to entity_links as data coverage grows

---

## Collection Status

| Collection | Count | Target | Status |
|------------|-------|--------|--------|
| Patents | 2,941 | ~2,941 | Complete |
| Grants | ~17,757 | ~50,000 | ~35% done |
| Researchers | 10,000 | ~242,000 | ~4% done (API limit issue) |
| Policies | 0 | TBD | Not started |
| FDA Calendar | 0 | TBD | Not started |
| Portfolio | 115 | 115 | Complete |

## Known Issues

### Researchers API Limit
The `/api/export` endpoint on Talent Scout defaults to `limit=10000`.
To get all ~242k researchers, need to either:
1. Pass higher limit: `?limit=250000` (may timeout)
2. Add pagination support to fetch in chunks

## Resume Commands

### Continue Grants Ingestion
```bash
# Run this ~16 more times (or in a loop) to complete grants
curl -X POST "https://kdtneo.up.railway.app/api/neo-ingest?secret=<SECRET>&source=grants&limit=2000"
```

### Check Current Stats
```bash
curl "https://kdtneo.up.railway.app/api/neo-stats"
```

### Ingest Other Sources
```bash
# Policies
curl -X POST "https://kdtneo.up.railway.app/api/neo-ingest?secret=<SECRET>&source=policies"

# FDA Calendar
curl -X POST "https://kdtneo.up.railway.app/api/neo-ingest?secret=<SECRET>&source=fda_calendar"
```

## Notes

- Deduplication is handled automatically - re-running won't create duplicates
- Each batch of 2,000 documents takes ~2-3 minutes
- Use `limit` parameter to avoid Railway's 15-minute timeout
- Data is persisted after each batch via ChromaDB

## Future Improvements

### Efficiency Issues
Current process is slow because:
1. **Synchronous HTTP fetches** - fetches entire dataset before processing
2. **Sequential embedding** - embeds one batch at a time
3. **No streaming** - can't start processing while still fetching
4. **Memory heavy** - loads all data into memory

### Potential Solutions
1. **Background job queue** (Redis + Celery/RQ)
   - Decouple API request from actual ingestion
   - Run ingestion as async background job
   - Return job ID immediately, poll for status

2. **Streaming/pagination on source APIs**
   - Fetch data in pages instead of all at once
   - Process each page as it arrives

3. **Batch embeddings with GPU** (if available)
   - Current: CPU-based sentence-transformers
   - Could use: OpenAI embeddings API (faster, costs $)

4. **Incremental sync**
   - Track last_updated timestamps
   - Only fetch/embed new or changed documents

5. **Pre-computed embeddings**
   - Compute embeddings at source services
   - RAG just stores pre-computed vectors
