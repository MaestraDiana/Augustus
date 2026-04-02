#!/usr/bin/env bash
# restart-backend.sh
# Kills any process holding port 8080, then starts uvicorn.
# Usage (from project root):  bash scripts/restart-backend.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "→ Clearing port 8080..."
if [ -f "$PROJECT_ROOT/backend/venv/bin/python" ]; then
    PYTHON_EXE="$PROJECT_ROOT/backend/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
else
    PYTHON_EXE="python"
fi

$PYTHON_EXE "$SCRIPT_DIR/kill-port.py" 8080

echo "→ Starting uvicorn..."
cd "$PROJECT_ROOT/backend"
exec $PYTHON_EXE -m uvicorn augustus.api.app:app --port 8080 --host 127.0.0.1
