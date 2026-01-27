#!/bin/bash
# Sync local SQLite databases to the data/ directory for Neo SQL agent
# Run this before deploying or when you want to update the data

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/../data"

echo "Syncing databases to $DATA_DIR..."

# Create data directory if it doesn't exist
mkdir -p "$DATA_DIR"

# Copy databases with standardized names
echo "  Copying researchers database..."
cp ~/h_index_tracker/data/hindex.db "$DATA_DIR/researchers.db"

echo "  Copying patents database..."
cp ~/patent_warrior/data/patents.db "$DATA_DIR/patents.db"

echo "  Copying grants database..."
cp ~/grants_tracker/data/grants.db "$DATA_DIR/grants.db"

echo "  Copying policies database..."
cp ~/policy_tracker/data/policy_tracker.db "$DATA_DIR/policies.db"

echo "  Copying portfolio database..."
cp ~/portfolio_tracker_history/data/portfolio.db "$DATA_DIR/portfolio.db"

echo ""
echo "Done! Database sizes:"
du -h "$DATA_DIR"/*.db

echo ""
echo "Total size:"
du -sh "$DATA_DIR"
