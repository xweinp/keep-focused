#!/usr/bin/env bash
set -euo pipefail

# keep-focused – no-sudo, no-pip installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/xweinp/keep-focused/main/install.sh | bash
#   # or
#   git clone https://github.com/xweinp/keep-focused && ./install.sh
#   ./scripts/install.sh   # also works
#
# Env:
#   KEEP_FOCUSED_INSTALL_DIR  – where to put the app (default ~/.local/share/keep-focused)
#   KEEP_FOCUSED_BIN_DIR      – where to put the binary (default ~/.local/bin)
#   KEEP_FOCUSED_REPO         – override repo URL

REPO="${KEEP_FOCUSED_REPO:-https://github.com/xweinp/keep-focused}"
INSTALL_DIR="${KEEP_FOCUSED_INSTALL_DIR:-$HOME/.local/share/keep-focused}"
BIN_DIR="${KEEP_FOCUSED_BIN_DIR:-$HOME/.local/bin}"
BIN_PATH="$BIN_DIR/keep-focused"

is_tty() { [ -t 1 ]; }
green() { if is_tty; then printf "\033[32m%s\033[0m\n" "$*"; else printf "%s\n" "$*"; fi; }
yellow() { if is_tty; then printf "\033[33m%s\033[0m\n" "$*"; else printf "%s\n" "$*"; fi; }
red() { if is_tty; then printf "\033[31m%s\033[0m\n" "$*"; else printf "%s\n" "$*"; fi; }
dim() { if is_tty; then printf "\033[2m%s\033[0m\n" "$*"; else printf "%s\n" "$*"; fi; }

# 1. Check python3
if ! command -v python3 >/dev/null 2>&1; then
  red "✗ python3 not found. Debian has it by default – install with:"
  echo "    sudo apt update && sudo apt install -y python3"
  echo "  (this is the only thing that may need sudo; keep-focused itself does not)"
  exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$(python3 -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
  red "✗ python3 >= 3.9 required (found $PY_VER)"
  exit 1
fi
dim "✓ python3 $PY_VER found"

# 2. Determine source
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
SRC_DIR=""

# If this script is inside a checkout that has keep_focused/, use it
if [ -f "$SCRIPT_DIR/keep_focused/cli.py" ]; then
  SRC_DIR="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../keep_focused/cli.py" ]; then
  SRC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -f "./keep_focused/cli.py" ]; then
  SRC_DIR="$(pwd)"
fi

TMP_CLONE=""
cleanup() {
  if [ -n "${TMP_CLONE:-}" ] && [ -d "$TMP_CLONE" ]; then
    rm -rf "$TMP_CLONE"
  fi
}
trap cleanup EXIT

if [ -z "$SRC_DIR" ]; then
  dim "→ Downloading keep-focused from $REPO..."
  TMP_CLONE="$(mktemp -d)"
  if command -v git >/dev/null 2>&1; then
    git clone --depth 1 "$REPO" "$TMP_CLONE/repo" >/dev/null 2>&1
    SRC_DIR="$TMP_CLONE/repo"
  else
    # Fallback: curl tarball
    if ! command -v curl >/dev/null 2>&1; then
      red "✗ Need git or curl to download. Install one and retry."
      exit 1
    fi
    mkdir -p "$TMP_CLONE/repo"
    # Try main branch tarball
    TARBALL="$REPO/archive/refs/heads/main.tar.gz"
    dim "  curl $TARBALL"
    curl -fsSL "$TARBALL" | tar -xz -C "$TMP_CLONE" --strip-components=1 2>/dev/null || {
      # Try without strip if structure differs
      curl -fsSL "$TARBALL" -o "$TMP_CLONE/t.tgz"
      tar -xz -f "$TMP_CLONE/t.tgz" -C "$TMP_CLONE/repo" --strip-components=1 2>/dev/null || tar -xz -f "$TMP_CLONE/t.tgz" -C "$TMP_CLONE" 2>/dev/null
      # find keep_focused
      FOUND="$(find "$TMP_CLONE" -name "cli.py" -path "*/keep_focused/*" 2>/dev/null | head -1 || true)"
      if [ -n "$FOUND" ]; then
        SRC_DIR="$(dirname "$(dirname "$FOUND")")"
      fi
    }
    if [ -z "${SRC_DIR:-}" ]; then
      # search again
      FOUND="$(find "$TMP_CLONE" -name "cli.py" -path "*/keep_focused/*" 2>/dev/null | head -1 || true)"
      if [ -n "$FOUND" ]; then
        SRC_DIR="$(dirname "$(dirname "$FOUND")")"
      else
        SRC_DIR="$TMP_CLONE/repo"
      fi
    fi
  fi

  if [ ! -f "$SRC_DIR/keep_focused/cli.py" ]; then
    red "✗ Failed to download keep-focused (no keep_focused/cli.py in $SRC_DIR)"
    ls -la "$SRC_DIR" 2>&1 | head -20 || true
    exit 1
  fi
  green "✓ Downloaded to $SRC_DIR"
else
  dim "→ Using local source: $SRC_DIR"
fi

# 3. Install files
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

# Copy app files (no pip, no build – just copy)
# Exclude .git, .claude, __pycache__
dim "→ Installing to $INSTALL_DIR..."
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git' --exclude '.gitignore' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude '.claude' --exclude '.venv' --exclude 'venv' --exclude 'build' --exclude 'dist' \
    "$SRC_DIR/keep_focused" "$INSTALL_DIR/"
  # also copy metadata for debugging
  cp -f "$SRC_DIR/pyproject.toml" "$INSTALL_DIR/" 2>/dev/null || true
  cp -f "$SRC_DIR/README.md" "$INSTALL_DIR/" 2>/dev/null || true
  mkdir -p "$INSTALL_DIR/systemd"
  cp -f "$SRC_DIR/systemd/keep-focused.service" "$INSTALL_DIR/systemd/" 2>/dev/null || true
else
  # fallback: rm + cp
  rm -rf "$INSTALL_DIR/keep_focused"
  cp -r "$SRC_DIR/keep_focused" "$INSTALL_DIR/"
  find "$INSTALL_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
  find "$INSTALL_DIR" -name "*.pyc" -delete 2>/dev/null || true
  cp -f "$SRC_DIR/pyproject.toml" "$INSTALL_DIR/" 2>/dev/null || true
  cp -f "$SRC_DIR/README.md" "$INSTALL_DIR/" 2>/dev/null || true
  mkdir -p "$INSTALL_DIR/systemd"
  cp -f "$SRC_DIR/systemd/keep-focused.service" "$INSTALL_DIR/systemd/" 2>/dev/null || true
fi

# Make sure systemd.py etc are there
if [ ! -f "$INSTALL_DIR/keep_focused/cli.py" ]; then
  red "✗ Install failed – cli.py missing after copy"
  exit 1
fi

# 4. Create wrapper binary (no sudo, no pip)
cat > "$BIN_PATH" <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
# keep-focused wrapper – runs via python3, no pip needed
INSTALL_DIR="${KEEP_FOCUSED_INSTALL_DIR:-$HOME/.local/share/keep-focused}"
if [ -n "${KEEP_FOCUSED_INSTALL_DIR:-}" ]; then
  INSTALL_DIR="$KEEP_FOCUSED_INSTALL_DIR"
fi
export PYTHONPATH="$INSTALL_DIR:${PYTHONPATH:-}"
exec python3 -m keep_focused "$@"
WRAPPER
chmod +x "$BIN_PATH"
green "✓ Binary installed at $BIN_PATH"

# 5. PATH check
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
  yellow "⚠ $BIN_DIR is not in your PATH"
  echo "  Add it for this session:"
  echo "    export PATH=\"$BIN_DIR:\$PATH\""
  echo "  And persist it (pick one):"
  echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
  echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
  # Try to auto-detect shell rc
  SHELL_RC=""
  if [ -n "${ZSH_VERSION:-}" ] || [ "${SHELL:-}" = "/bin/zsh" ] || [ "${SHELL:-}" = "/usr/bin/zsh" ]; then
    SHELL_RC="$HOME/.zshrc"
  else
    SHELL_RC="$HOME/.bashrc"
  fi
  if [ -f "$SHELL_RC" ] && ! grep -q ".local/bin" "$SHELL_RC" 2>/dev/null; then
    echo ""
    read -r -p "Add to $SHELL_RC now? [Y/n] " ans </dev/tty || ans="y"
    ans="${ans:-y}"
    if [[ "$ans" =~ ^[Yy] ]]; then
      echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
      green "✓ Added to $SHELL_RC (restart shell or run: export PATH=\"$BIN_DIR:\$PATH\")"
    fi
  fi
else
  dim "✓ $BIN_DIR is in PATH"
fi

# 6. Verify
if command -v keep-focused >/dev/null 2>&1; then
  dim "✓ keep-focused found: $(command -v keep-focused)"
else
  yellow "  Run with full path for now: $BIN_PATH"
fi

echo ""
green "✓ keep-focused installed!"
echo ""
echo "  Launch the app:"
if echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
  echo "    keep-focused"
else
  echo "    $BIN_PATH"
  echo "    # or after fixing PATH:"
  echo "    keep-focused"
fi
echo ""
echo "  What happens next:"
echo "    • App will suggest facebook.com, x.com, linkedin.com, spotify.com..."
echo "    • Choose sites to block, set a 20+ char password"
echo "    • Blocks via /etc/hosts (Chrome, Firefox…) – sudo prompt only when needed"
echo "    • Autostart enabled so blocks persist after reboot"
echo ""
echo "  No sudo pip, no apt – just python3 (already on Debian)."
echo "  Uninstall: keep-focused → 6. Uninstall   or   rm -rf $INSTALL_DIR $BIN_PATH"
echo ""
dim "Happy focusing!"
