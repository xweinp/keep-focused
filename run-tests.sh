#!/usr/bin/env bash
set -euo pipefail
# Run keep-focused test suite – tries pytest first, falls back to stdlib runner

if command -v pytest >/dev/null 2>&1; then
  exec pytest "$@"
elif python3 -m pytest --version >/dev/null 2>&1; then
  exec python3 -m pytest "$@"
else
  echo "pytest not found, using fallback runner (no extra deps needed)..."
  exec python3 tests/run_tests.py "$@"
fi
