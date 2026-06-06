#!/bin/sh
# lint.sh — Run all linters. Exit 0 if everything passes, non-zero otherwise.
# Compatible with pi-CoWork CLI quality gates (exit 0 = pass, non-zero = fail).

# Resolve project root relative to this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || { echo "ERROR: Cannot cd to project root"; exit 1; }

ERRORS=0

# --- Helpers ---
run_check() {
    name="$1"
    shift
    echo ""
    echo "=== $name ==="
    if "$@"; then
        echo "✓ $name passed"
    else
        echo "✗ $name FAILED"
        ERRORS=$((ERRORS + 1))
    fi
}

check_tool() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "ERROR: '$1' is not installed or not on PATH."
        echo "  Install Python tools:  pip install ruff"
        echo "  Install JS tools:      npm install --no-save eslint@9.21.0 @eslint/js@9.21.0 globals@15.15.0 jscpd@3.5.10"
        exit 1
    fi
}

# --- Tool availability ---
check_tool ruff
check_tool npx

# --- Python ---
run_check "Ruff lint" ruff check .
run_check "Ruff format" ruff format --check .

# --- JavaScript ---
run_check "ESLint" npx eslint static/

# --- Duplication ---
run_check "jscpd (duplication)" npx jscpd --config .jscpd.json

# --- Summary ---
echo ""
if [ "$ERRORS" -eq 0 ]; then
    echo "=== All checks passed ==="
    exit 0
else
    echo "=== $ERRORS check(s) failed ==="
    exit 1
fi
