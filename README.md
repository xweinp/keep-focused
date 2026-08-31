# keep-focused

CLI app for Debian that blocks distracting websites system-wide — works in Chrome, Firefox, and any browser via `/etc/hosts`. Set up in the terminal, pick suggested sites, set a strong password, and stay blocked across reboots.

- **System-wide blocking** — `127.0.0.1` + `::1` for each domain + `www.` variant → all browsers
- **Suggested sites** — `facebook.com`, `x.com`, `linkedin.com`, `spotify.com`, … (13 presets)
- **Strong password** — minimum 20 characters, PBKDF2-HMAC-SHA256, required to unblock/disable/uninstall
- **Autostart** — `systemd` service re-applies blocks on every boot (`keep-focused apply`)

## Install (Debian)

```bash
# 1. Clone
git clone https://github.com/xweinp/keep-focused
cd keep-focused

# 2. Install dependencies (if pip missing)
sudo apt update && sudo apt install -y python3-pip

# 3. Install the CLI (editable) + systemd service
sudo ./scripts/install.sh
# — or manually —
sudo pip3 install .
# or without pip:
sudo python3 -m pip install .   # if pip is available as module
```

Alternatively run directly without installing:

```bash
sudo python3 -m keep_focused.cli setup
```

## Quick start

```bash
sudo keep-focused setup
```

Interactive flow:

1. Shows 13 suggested sites — defaults pre-selected: `facebook.com`, `x.com`, `linkedin.com`, `spotify.com`
2. Prompt: `Enter numbers comma-separated (e.g. 1,2,4,6)`, `a` for all, `ENTER` for defaults
3. Password: at least **20 characters** (entered twice, hidden)
4. Writes `/etc/keep-focused/config.json` (0600) + patches `/etc/hosts` with `# BEGIN keep-focused` block
5. Installs & enables `keep-focused.service` → blocks re-applied on boot

Non-interactive (scripting):

```bash
sudo keep-focused setup --sites facebook.com x.com youtube.com --password 'your-very-long-password-here!!'
```

## Usage

```bash
keep-focused status              # show blocked sites, active/hosts, autostart
keep-focused list                # list blocked sites
sudo keep-focused block youtube.com reddit.com   # block more (needs password)
sudo keep-focused add tiktok.com                 # alias
sudo keep-focused unblock spotify.com            # unblock (needs password)
sudo keep-focused remove x.com                   # alias
sudo keep-focused disable        # disable all blocking (needs password)
sudo keep-focused enable         # re-enable
sudo keep-focused passwd         # change password (needs old password)
sudo keep-focused uninstall      # remove blocks, service, config (needs password)

# internal – called by systemd on boot, no password needed
sudo keep-focused apply
```

All `block`/`unblock`/`disable`/`uninstall`/`passwd` commands prompt for the password you set (20+ chars, PBKDF2).

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

  Removal preserves all other hosts entries. Supports `https://`, `www.`, ports, paths — normalized.

- **Config**: `/etc/keep-focused/config.json` (or `$KEEP_FOCUSED_CONFIG` for testing):

  ```json
  {
    "password_hash": "...",
    "salt": "...",
    "blocked_sites": ["facebook.com", "x.com"],
    "enabled": true
  }
  ```

- **Autostart**: `/etc/systemd/system/keep-focused.service`:

  ```
  [Service]
  ExecStart=/usr/local/bin/keep-focused apply
  ```

  Enabled via `systemctl enable keep-focused`. Falls back with a warning if systemd unavailable.

## Suggested sites

`facebook.com`, `x.com`, `twitter.com`, `linkedin.com`, `spotify.com`, `instagram.com`, `youtube.com`, `reddit.com`, `tiktok.com`, `netflix.com`, `twitch.tv`, `discord.com`, `threads.net`

Defaults on first setup: `facebook.com`, `x.com`, `linkedin.com`, `spotify.com`.

## Development / testing

Uses only stdlib (`argparse`, `hashlib`, `getpass`, `pathlib`). No extra deps.

Mock hosts/config/service for tests:

```bash
KEEP_FOCUSED_HOSTS=/tmp/hosts KEEP_FOCUSED_CONFIG=/tmp/cfg.json KEEP_FOCUSED_SERVICE=/tmp/svc \
  python3 -m keep_focused.cli setup --password 'xxxxxxxxxxxxxxxxxxxx' --sites facebook.com
```

## Uninstall

```bash
sudo keep-focused uninstall
# or manually:
sudo rm /etc/systemd/system/keep-focused.service
sudo systemctl daemon-reload
sudo rm -rf /etc/keep-focused
# then clean hosts markers if any
```

## License

MIT
