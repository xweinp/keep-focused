#!/usr/bin/env bash
set -euo pipefail

# Install keep-focused on Debian
# Usage: sudo ./scripts/install.sh
# Or: pip install . && sudo keep-focused setup

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0"
  exit 1
fi

# Install package
if command -v pip3 >/dev/null 2>&1; then
  pip3 install --upgrade "$(dirname "$0")/.."
elif command -v pip >/dev/null 2>&1; then
  pip install --upgrade "$(dirname "$0")/.."
else
  echo "pip not found. Installing python3-pip..."
  apt-get update && apt-get install -y python3-pip
  pip3 install --upgrade "$(dirname "$0")/.."
fi

# Install systemd service if not already (setup will also do it)
SERVICE_SRC="$(dirname "$0")/../systemd/keep-focused.service"
SERVICE_DST="/etc/systemd/system/keep-focused.service"
if [[ -f "$SERVICE_SRC" && ! -f "$SERVICE_DST" ]]; then
  cp "$SERVICE_SRC" "$SERVICE_DST"
  # Don't enable yet – setup will enable after config is created
  systemctl daemon-reload || true
fi

echo "Installed. Now run: sudo keep-focused setup"
