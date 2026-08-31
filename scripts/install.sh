#!/usr/bin/env bash
set -euo pipefail
# Legacy wrapper – delegates to ../install.sh (no sudo, no pip)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_INSTALL="$SCRIPT_DIR/../install.sh"
if [ -f "$ROOT_INSTALL" ]; then
  exec bash "$ROOT_INSTALL" "$@"
else
  echo "install.sh not found at $ROOT_INSTALL"
  exit 1
fi
