#!/usr/bin/env bash
# restart-backend.sh
# Kills any process holding port 8080, then starts uvicorn.
# Usage (from project root):  bash scripts/restart-backend.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "→ Clearing port 8080..."
python "$SCRIPT_DIR/kill-port.py" 8080

echo "→ Starting uvicorn..."
cd "$PROJECT_ROOT/backend"
exec python -m uvicorn augustus.api.app:app --port 8080 --host 127.0.0.1
