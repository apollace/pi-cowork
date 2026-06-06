#!/bin/sh
# lint-fix.sh — Auto-fix what can be auto-fixed. Review changes before committing.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || { echo "ERROR: Cannot cd to project root"; exit 1; }

ERRORS=0

run_fix() {
    name="$1"
    shift
    echo ""
    echo "=== $name ==="
    if "$@"; then
        echo "✓ $name completed"
    else
        echo "⚠ $name exited with errors (some issues may need manual fix)"
        ERRORS=$((ERRORS + 1))
    fi
}

check_tool() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "ERROR: '$1' is not installed or not on PATH."
        exit 1
    fi
}

check_tool ruff
check_tool npx

run_fix "Ruff auto-fix" ruff check . --fix
run_fix "Ruff format" ruff format .
run_fix "ESLint auto-fix" npx eslint static/ --fix

echo ""
if [ "$ERRORS" -eq 0 ]; then
    echo "=== All auto-fixes completed cleanly ==="
    exit 0
else
    echo "=== Some fixes had issues — review output above ==="
    exit 1
fi
