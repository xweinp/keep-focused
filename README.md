# keep-focused

Interactive CLI app for Debian that blocks distracting websites **system-wide** — works in **Chrome, Firefox, any browser** via `/etc/hosts`. Like `opencode` or `claude code`: install with one command, no `sudo`, no `pip`, then launch the app and stay focused.

- **System-wide** — `127.0.0.1` + `::1` for each domain + `www.` variant
- **Suggested sites** — `facebook.com`, `x.com`, `linkedin.com`, `spotify.com`, … (13 presets, arrow + Space to toggle)
- **Strong password** — ≥20 characters, PBKDF2-HMAC-SHA256, required to unblock/disable/uninstall
- **Autostart** — `systemd` service re-applies blocks on every boot (`keep-focused apply`)

## Install (no sudo, no pip) — like opencode

```bash
# One-liner (curl | bash) — recommended
curl -fsSL https://raw.githubusercontent.com/xweinp/keep-focused/main/install.sh | bash

# Or from a clone
git clone https://github.com/xweinp/keep-focused
cd keep-focused
./install.sh
```

What it does:
- Checks `python3 >= 3.9` (already on Debian)
- Copies the app to `~/.local/share/keep-focused` (no root, no pip, no apt)
- Creates `~/.local/bin/keep-focused` wrapper → `python3 -m keep_focused` (`PYTHONPATH=~/.local/share/keep-focused`)
- Adds `~/.local/bin` to `PATH` if needed and prints next steps

No `sudo apt install python3-pip`, no `pip install`, no root.

## Launch the app

```bash
keep-focused
# if PATH not yet reloaded:
~/.local/bin/keep-focused
# or
export PATH="$HOME/.local/bin:$PATH" && keep-focused
```

You get an interactive menu (arrow navigation):

```
  ╔══════════════════════════════════════════╗
  ║         keep-focused  — stay sharp      ║
  ╚══════════════════════════════════════════╝

  Main menu
  ──────────────────────────────────────────────────
   Sites:   4 blocked  (facebook.com, x.com...)
   State:   🟢 ACTIVE  (hosts active, autostart on)

  › View blocked sites
   Block more sites (suggested + custom)
   Unblock sites
   Toggle enable/disable
   Change password
   Update (check & install latest)
   Uninstall
   Quit

  ↑/↓ to move • Enter to select • q/Esc to quit
```

**First run** goes to **Setup**:
1. Checkbox list of 13 suggested sites (defaults `facebook.com`, `x.com`, `linkedin.com`, `spotify.com` pre-checked)
   - **↑/↓ to move, Space to toggle, Enter done, a=all, n=none, c=custom, q/Esc cancel** (falls back to `1/q` typing when not a TTY)
2. Set a password **≥20 chars** (hidden, twice). You need it to unblock/disable.
3. The app then writes `~/.config/keep-focused/config.json` (0600) + patches `/etc/hosts` with `# BEGIN keep-focused` (uses `sudo` only here, prompts for your sudo password if needed) + enables `systemd` service so blocks persist after reboot.

All browsers now show connection errors for blocked sites.

## How it works

- **Hosts file**: inserts between markers:

  ```
  # BEGIN keep-focused
  127.0.0.1 facebook.com
  ::1 facebook.com
  127.0.0.1 www.facebook.com
  ::1 www.facebook.com
  # END keep-focused
  ```

  Removal preserves other entries. Handles `https://`, `www.`, ports, paths — normalized to bare domain via `normalize_domain()` in `keep_focused/hosts.py:22`.

- **Config**: `~/.config/keep-focused/config.json` (or `$XDG_CONFIG_HOME`, fallback to `/etc/keep-focused/config.json` for legacy `sudo` setups). Override for tests via `$KEEP_FOCUSED_CONFIG`.

  ```json
  {
    "password_hash": "...",
    "salt": "...",
    "blocked_sites": ["facebook.com", "x.com"],
    "enabled": true
  }
  ```

- **Autostart**: tries **system service** (`/etc/systemd/system/keep-focused.service` via `sudo tee` if available), falls back to **user service** (`~/.config/systemd/user/keep-focused.service` + `systemctl --user enable`). Both run `keep-focused apply` on boot; logic in `keep_focused/systemd.py:1`.

- **Privileges**: installer never needs `sudo`. Only **runtime** `apply_block()` in `keep_focused/hosts.py:72` uses `sudo tee`/`pkexec` if `/etc/hosts` is not writable, so you see the normal sudo prompt inside the app.

## Update

```bash
keep-focused update          # self-update, no sudo/pip (like opencode)
keep-focused update --check  # check only
keep-focused update --force  # force reinstall even if up to date
```

Or just `keep-focused` → `Update (check & install latest)` in the menu.

**If you installed before `update` existed** (old version has no `keep-focused update`), just re-run the installer – it’s idempotent and preserves your config/blocks:

```bash
curl -fsSL https://raw.githubusercontent.com/xweinp/keep-focused/main/install.sh | bash
# or if you cloned:
git pull && ./install.sh
```

After that `keep-focused update` will be available.

## Scripting (optional, no TUI)

The app also supports commands for automation (password required where noted):

```bash
keep-focused status
keep-focused block youtube.com reddit.com
keep-focused unblock spotify.com
keep-focused disable
keep-focused enable
keep-focused passwd
keep-focused update --check
keep-focused uninstall
keep-focused apply   # internal – called by systemd on boot, no password
```

But the primary way is just `keep-focused` → interactive app.

## Advanced: pip install (legacy)

If you prefer pip:

```bash
pip install .   # or pipx
keep-focused    # still launches the TUI
```

## Uninstall

From the app: `keep-focused` → `Update/Uninstall` → `Uninstall` (requires password) — cleans hosts, systemd, config.

Or manually:

```bash
rm -rf ~/.local/share/keep-focused ~/.local/bin/keep-focused
rm -rf ~/.config/keep-focused
# if you had a system install:
sudo rm -f /etc/systemd/system/keep-focused.service /etc/keep-focused/config.json
systemctl --user disable keep-focused.service 2>/dev/null; sudo systemctl disable keep-focused.service 2>/dev/null
```

## Development / testing

Only stdlib (`argparse`, `hashlib`, `getpass`, `pathlib`, `curses`-free). No deps.

Mock hosts/config/service:

```bash
KEEP_FOCUSED_HOSTS=/tmp/hosts KEEP_FOCUSED_CONFIG=/tmp/cfg.json KEEP_FOCUSED_SERVICE=/tmp/svc python3 -m keep_focused.cli status
KEEP_FOCUSED_HOSTS=/tmp/hosts KEEP_FOCUSED_CONFIG=/tmp/cfg.json python3 -m keep_focused.tui  # runs TUI with mocks
```

## Suggested sites

`facebook.com`, `x.com`, `twitter.com`, `linkedin.com`, `spotify.com`, `instagram.com`, `youtube.com`, `reddit.com`, `tiktok.com`, `netflix.com`, `twitch.tv`, `discord.com`, `threads.net` — see `keep_focused/__init__.py:6`.

## License

MIT
