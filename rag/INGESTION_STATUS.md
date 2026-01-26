# RAG Ingestion Status

Last updated: 2026-01-26

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
curl -X POST "https://kdtrag.up.railway.app/api/rag-ingest?secret=<SECRET>&source=grants&limit=2000"
```

### Check Current Stats
```bash
curl "https://kdtrag.up.railway.app/api/rag-stats"
```

### Ingest Other Sources
```bash
# Policies
curl -X POST "https://kdtrag.up.railway.app/api/rag-ingest?secret=<SECRET>&source=policies"

# FDA Calendar
curl -X POST "https://kdtrag.up.railway.app/api/rag-ingest?secret=<SECRET>&source=fda_calendar"
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
