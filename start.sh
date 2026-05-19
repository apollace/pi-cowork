#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$APP_DIR/pi-cowork.pid"
LOGFILE="$APP_DIR/pi-cowork.log"

if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "pi-CoWork is already running (PID $PID)"
        exit 0
    else
        rm -f "$PIDFILE"
    fi
fi

cd "$APP_DIR"

while true; do
    rm -f "$APP_DIR/.reload"
    python3 app.py >> "$LOGFILE" 2>&1 &
    PYTHON_PID=$!
    echo "$PYTHON_PID" > "$PIDFILE"
    echo "pi-CoWork started on PID $PYTHON_PID"

    # Wait for the process to exit
    wait "$PYTHON_PID" || true
    rm -f "$PIDFILE"

    if [ ! -f "$APP_DIR/.reload" ]; then
        break
    fi
    echo "Reload sentinel found; restarting..."
done
