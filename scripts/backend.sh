#!/usr/bin/env bash
# Backend dev server manager for Augustus
# Usage: ./scripts/backend.sh [start|stop|restart]
#
# Starts uvicorn WITHOUT --reload. The --reload flag uses filesystem watchers
# that don't fire reliably on network drives (e.g. Z:\ on Windows), causing
# the process to hang and require manual kill. Restart the script instead.
#
# On Windows, run from Git Bash.

set -euo pipefail

PORT="${AUGUSTUS_PORT:-8080}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
PID_FILE="$PROJECT_ROOT/.backend.pid"

kill_port() {
    # Kill any process currently listening on the port.
    # Works on Windows (via Git Bash) and Unix.
    if command -v netstat &>/dev/null; then
        local pid
        pid=$(netstat -ano 2>/dev/null \
            | grep "LISTENING" \
            | grep ":${PORT}[[:space:]]" \
            | awk '{print $NF}' \
            | head -1)
        if [ -n "$pid" ] && [ "$pid" != "0" ]; then
            echo "Killing existing process on port $PORT (PID $pid)..."
            # Use Python to run taskkill — avoids Git Bash permission issues
            python -c "import subprocess; subprocess.run(['taskkill', '/PID', '$pid', '/F'], check=False)" \
                2>/dev/null \
                || kill -9 "$pid" 2>/dev/null \
                || true
            sleep 1
        fi
    fi

    # Also try PID file if it exists
    if [ -f "$PID_FILE" ]; then
        local stored_pid
        stored_pid=$(cat "$PID_FILE")
        if [ -n "$stored_pid" ]; then
            kill "$stored_pid" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
    fi
}

cmd_start() {
    kill_port

    echo "Starting Augustus backend on port $PORT..."
    cd "$BACKEND_DIR"

    # Start uvicorn in the background, log to stdout
    uvicorn augustus.api.app:app --port "$PORT" &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    echo "Backend started (PID $pid). Waiting for health check..."

    local attempts=0
    until curl -sf "http://127.0.0.1:${PORT}/api/orchestrator/status" &>/dev/null; do
        attempts=$((attempts + 1))
        if [ $attempts -ge 30 ]; then
            echo "Error: Backend did not become healthy after 30 seconds."
            cmd_stop
            exit 1
        fi
        sleep 1
    done

    echo "Backend ready at http://127.0.0.1:${PORT}"
}

cmd_stop() {
    echo "Stopping Augustus backend..."
    kill_port
    echo "Done."
}

cmd_restart() {
    cmd_stop
    cmd_start
}

case "${1:-start}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    *)
        echo "Usage: ./scripts/backend.sh [start|stop|restart]"
        echo "  start    Kill any existing process on port $PORT, then start backend"
        echo "  stop     Kill the backend process"
        echo "  restart  Stop then start"
        exit 1
        ;;
esac
