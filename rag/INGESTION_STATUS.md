# RAG Ingestion Status

Last updated: 2026-01-26

## Collection Status

| Collection | Count | Target | Status |
|------------|-------|--------|--------|
| Patents | 2,941 | ~2,941 | Complete |
| Grants | ~17,757 | ~50,000 | ~35% done |
| Researchers | 10,000 | 10,000 | Complete |
| Policies | 0 | TBD | Not started |
| FDA Calendar | 0 | TBD | Not started |
| Portfolio | 115 | 115 | Complete |

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
