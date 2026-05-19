#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$APP_DIR/pi-cowork.pid"

if [ ! -f "$PIDFILE" ]; then
    echo "pi-CoWork is not running (no PID file)"
    exit 0
fi

PID=$(cat "$PIDFILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "pi-CoWork stopped (PID $PID)"
else
    echo "pi-CoWork was not running (stale PID file)"
fi

rm -f "$PIDFILE"
rm -f "$APP_DIR/.reload"
