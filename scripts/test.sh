#!/bin/sh
# test.sh — Run the pytest suite. Exit 0 on success, non-zero on failure.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || { echo "ERROR: Cannot cd to project root"; exit 1; }

if ! command -v pytest >/dev/null 2>&1; then
    echo "ERROR: pytest is not installed."
    echo "  Install:  pip install pytest"
    exit 1
fi

PYTHONPATH="$PROJECT_ROOT" pytest tests/ -v "$@"
