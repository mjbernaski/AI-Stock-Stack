#!/usr/bin/env bash
# Start (or restart) the AI Stock Stack server on port 1111.
set -euo pipefail

cd "$(dirname "$0")"

PORT=1111

# Kill whatever is already listening on the port (Flask's reloader means
# there can be more than one PID).
PIDS=$(lsof -ti tcp:"$PORT" || true)
if [ -n "$PIDS" ]; then
    echo "Killing existing process(es) on port $PORT: $PIDS"
    kill $PIDS 2>/dev/null || true
    sleep 1
    PIDS=$(lsof -ti tcp:"$PORT" || true)
    if [ -n "$PIDS" ]; then
        echo "Force killing: $PIDS"
        kill -9 $PIDS 2>/dev/null || true
        sleep 1
    fi
fi

source venv/bin/activate
echo "Starting app.py on port $PORT..."

# Python block-buffers stdout when it is a file rather than a terminal, so a
# redirected log sits empty for a long time. Progress lines matter more here
# than the buffering does.
export PYTHONUNBUFFERED=1

exec python app.py
