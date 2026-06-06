#!/bin/sh
# test.sh — Run the pytest suite. Exit 0 on success, non-zero on failure.
# Works from any directory; finds project root automatically.

set -e

find_project_root() {
    dir="$(pwd)"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/pyproject.toml" ] && [ -d "$dir/pi_cowork" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    script_dir="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
    if [ -n "$script_dir" ] && [ -f "$script_dir/../pyproject.toml" ]; then
        echo "$(cd "$script_dir/.." && pwd)"
        return 0
    fi
    return 1
}

PROJECT_ROOT="$(find_project_root)"
if [ -z "$PROJECT_ROOT" ]; then
    echo "ERROR: Cannot find pi-CoWork project root."
    exit 1
fi

cd "$PROJECT_ROOT"

if ! command -v pytest >/dev/null 2>&1; then
    echo "ERROR: pytest is not installed."
    echo "  Install:  pip install pytest"
    exit 1
fi

PYTHONPATH="$PROJECT_ROOT" pytest tests/ -v "$@"
