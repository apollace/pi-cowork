#!/bin/sh
# lint.sh — Run all linters. Exit 0 if everything passes, non-zero otherwise.
# Designed to work as a pi-CoWork CLI quality gate: runs from any directory,
# finds the project root automatically, fails fast if tools are missing.

set -e

# --- Find project root ---
# Strategy: walk up from CWD looking for pyproject.toml + pi_cowork/ dir.
# This works even when invoked from a board working directory or via absolute path.
find_project_root() {
    dir="$(pwd)"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/pyproject.toml" ] && [ -d "$dir/pi_cowork" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    # Fallback: resolve relative to script location
    script_dir="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
    if [ -n "$script_dir" ] && [ -f "$script_dir/../pyproject.toml" ]; then
        echo "$(cd "$script_dir/.." && pwd)"
        return 0
    fi
    return 1
}

PROJECT_ROOT="$(find_project_root)"
if [ -z "$PROJECT_ROOT" ]; then
    echo "ERROR: Cannot find pi-CoWork project root (looked for pyproject.toml + pi_cowork/)."
    echo "  If this is a quality gate, make sure the board working directory is inside the repo."
    exit 1
fi

cd "$PROJECT_ROOT"

ERRORS=0

# --- Helpers ---
run_check() {
    name="$1"
    shift
    printf '\n=== %s ===\n' "$name"
    if "$@"; then
        printf '✓ %s passed\n' "$name"
    else
        printf '✗ %s FAILED\n' "$name"
        ERRORS=$((ERRORS + 1))
    fi
}

check_tool() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf "ERROR: '%s' is not installed or not on PATH.\n" "$1"
        printf "  Install Python tools:  pip install ruff\n"
        printf "  Install JS tools:      npm install --no-save eslint@9.21.0 @eslint/js@9.21.0 globals@15.15.0 jscpd@3.5.10\n"
        exit 1
    fi
}

# --- Tool availability ---
check_tool ruff
check_tool npx

# Verify node_modules exists so npx doesn't try to auto-install inside a gate
if [ ! -d "$PROJECT_ROOT/node_modules" ]; then
    printf "ERROR: node_modules/ not found in %s\n" "$PROJECT_ROOT"
    printf "  Run:  npm install --no-save eslint@9.21.0 @eslint/js@9.21.0 globals@15.15.0 jscpd@3.5.10\n"
    exit 1
fi

# --- Python ---
run_check "Ruff lint" ruff check .
run_check "Ruff format" ruff format --check .

# --- JavaScript ---
run_check "ESLint" npx --no-install eslint static/

# --- Duplication ---
run_check "jscpd (duplication)" npx --no-install jscpd --config .jscpd.json

# --- Summary ---
printf '\n'
if [ "$ERRORS" -eq 0 ]; then
    printf '=== All checks passed ===\n'
    exit 0
else
    printf '=== %s check(s) failed ===\n' "$ERRORS"
    exit 1
fi
