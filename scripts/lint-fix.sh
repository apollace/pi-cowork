#!/bin/sh
# lint-fix.sh — Auto-fix what can be auto-fixed. Review changes before committing.
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

ERRORS=0

run_fix() {
    name="$1"
    shift
    printf '\n=== %s ===\n' "$name"
    if "$@"; then
        printf '✓ %s completed\n' "$name"
    else
        printf '⚠ %s exited with errors (some issues may need manual fix)\n' "$name"
        ERRORS=$((ERRORS + 1))
    fi
}

check_tool() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf "ERROR: '%s' is not installed or not on PATH.\n" "$1"
        exit 1
    fi
}

check_tool ruff
check_tool npx

if [ ! -d "$PROJECT_ROOT/node_modules" ]; then
    printf "ERROR: node_modules/ not found. Run npm install.\n"
    exit 1
fi

run_fix "Ruff auto-fix" ruff check . --fix
run_fix "Ruff format" ruff format .
run_fix "ESLint auto-fix" npx --no-install eslint static/ --fix

printf '\n'
if [ "$ERRORS" -eq 0 ]; then
    printf '=== All auto-fixes completed cleanly ===\n'
    exit 0
else
    printf '=== Some fixes had issues — review output above ===\n'
    exit 1
fi
