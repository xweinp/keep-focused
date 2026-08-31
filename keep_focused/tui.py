"""Interactive CLI app (TUI) for keep-focused – like opencode/claude code.

Run `keep-focused` without args to launch this app.
Now with arrow navigation: Up/Down + Enter, Space to toggle.
"""

import os
import sys
import time
from pathlib import Path

from . import DEFAULT_SELECTED, SUGGESTED_SITES
from .auth import MIN_PASSWORD_LENGTH, hash_password, prompt_new_password, prompt_password, verify_password
from .config import config_location, default_config, load_config, save_config
from .hosts import apply_block, clear_block, get_blocked_from_hosts, is_block_active, normalize_domain
from .keys import HIDE_CURSOR, REVERSE, SHOW_CURSOR, is_interactive, read_key
from .systemd import install_service, is_service_enabled, uninstall_service

# ANSI helpers – keep it lightweight, no external deps
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
CLEAR = "\033[2J\033[H"


BANNER = f"""{BOLD}{CYAN}
  ╔══════════════════════════════════════════╗
  ║         keep-focused  — stay sharp      ║
  ║   Block distractions system-wide        ║
  ║   Works in Chrome, Firefox, any browser║
  ╚══════════════════════════════════════════╝{RESET}
"""


def _pause(msg: str = "Press ENTER to continue...") -> None:
    try:
        input(f"\n{DIM}{msg}{RESET}")
    except (EOFError, KeyboardInterrupt):
        print()


def _clear() -> None:
    if sys.stdout.isatty():
        sys.stdout.write(CLEAR)
        sys.stdout.flush()


def _header(title: str) -> None:
    _clear()
    print(BANNER)
    print(f"{BOLD}{title}{RESET}")
    print(f"{DIM}{'─' * 50}{RESET}")


def _status_line(cfg: dict | None) -> None:
    if cfg is None:
        print(f"{YELLOW}⚙  Not set up yet{RESET}  → run Setup\n")
        return
    enabled = cfg.get("enabled", True)
    blocked = cfg.get("blocked_sites", [])
    active = is_block_active()
    svc = is_service_enabled()
    loc = config_location()
    print(f" Config:  {DIM}{loc}{RESET}")
    print(f" Sites:   {BOLD}{len(blocked)}{RESET} blocked  {DIM}({', '.join(sorted(blocked)[:3])}{'...' if len(blocked)>3 else ''}){RESET}" if blocked else f" Sites:   {DIM}(none){RESET}")
    print(f" State:   {'🟢' if enabled and active else '🔴'}  {'ACTIVE' if enabled and active else 'DISABLED'}  {DIM}(hosts {'active' if active else 'inactive'}, autostart {'on' if svc else 'off'}){RESET}")
    print()


def _verify_or_exit(cfg: dict) -> bool:
    try:
        pw = prompt_password("Enter password to authorize: ")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return False
    if not verify_password(pw, cfg["salt"], cfg["password_hash"]):
        print(f"{RED}✗ Wrong password.{RESET}")
        time.sleep(1)
        return False
    return True


# ---------------------------------------------------------------------------
# Legacy (fallback) site selector – used when not a TTY or in tests
# ---------------------------------------------------------------------------
def _select_sites_interactive_legacy(current: set[str] | None = None, title: str = "Select sites to block") -> list[str] | None:
    selected: set[str] = set(current) if current is not None else set(DEFAULT_SELECTED)
    while True:
        _header(title)
        print(f"{DIM}Toggle by number,  a=all  n=none  d=done  q=cancel  c=custom domain{RESET}\n")
        for i, site in enumerate(SUGGESTED_SITES, 1):
            checked = "☑" if site in selected else "☐"
            color = GREEN if site in selected else DIM
            default_mark = f" {DIM}[suggested]{RESET}" if site in DEFAULT_SELECTED else ""
            print(f"  {color}{i:2}. {checked} {site}{default_mark}{RESET}")
        if selected:
            print(f"\n{DIM}Selected: {', '.join(sorted(selected))}{RESET}")
        else:
            print(f"\n{DIM}Selected: (none){RESET}")
        print(f"\n{DIM}Custom domains in selection: {', '.join(s for s in selected if s not in SUGGESTED_SITES) or '(none)'}{RESET}")

        try:
            raw = input(f"\n{BOLD}↳{RESET} Enter number to toggle, or a/n/d/q/c: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw in ("d", "done", ""):
            break
        if raw in ("q", "quit", "cancel"):
            return None
        if raw == "a":
            selected = set(SUGGESTED_SITES)
            continue
        if raw == "n":
            selected = set()
            continue
        if raw in ("c", "custom"):
            try:
                custom = input("  Enter custom domain (e.g. youtube.com) or comma-separated: ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not custom:
                continue
            for part in custom.replace(" ", "").split(","):
                if not part:
                    continue
                d = normalize_domain(part)
                if not d or "." not in d:
                    print(f"  {RED}✗ Invalid domain: {part}{RESET}")
                    time.sleep(0.7)
                    continue
                selected.add(d)
            continue
        parts = raw.replace(" ", "").split(",")
        any_handled = False
        for part in parts:
            if not part:
                continue
            try:
                idx = int(part)
                if 1 <= idx <= len(SUGGESTED_SITES):
                    site = SUGGESTED_SITES[idx - 1]
                    if site in selected:
                        selected.remove(site)
                    else:
                        selected.add(site)
                    any_handled = True
                else:
                    print(f"  {RED}✗ Out of range: {part}{RESET}")
                    time.sleep(0.7)
            except ValueError:
                d = normalize_domain(part)
                if d and "." in d:
                    if d in selected:
                        selected.remove(d)
                    else:
                        selected.add(d)
                    any_handled = True
                else:
                    print(f"  {RED}✗ Invalid: {part}{RESET}")
                    time.sleep(0.7)
        if any_handled:
            continue

    return sorted(selected)


# ---------------------------------------------------------------------------
# Arrow-based site selector
# ---------------------------------------------------------------------------
def _arrow_select_sites(current: set[str] | None, title: str) -> list[str] | None:
    selected: set[str] = set(current) if current is not None else set(DEFAULT_SELECTED)
    idx = 0
    # Hide cursor for arrow UI
    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()
    try:
        while True:
            _header(title)
            print(f"{DIM}↑/↓ move • Space toggle • Enter done • a=all n=none c=custom • q/Esc cancel{RESET}\n")
            for i, site in enumerate(SUGGESTED_SITES):
                checked = "☑" if site in selected else "☐"
                # Highlighted line: reverse + bold, others dim/green
                if i == idx:
                    # Reverse video for highlighted line
                    default_mark = f" {DIM}[suggested]{RESET}{REVERSE}" if site in DEFAULT_SELECTED else ""
                    # Need to reset after reverse
                    print(f"{REVERSE}  {i+1:2}. {checked} {site}{default_mark}  {RESET}")
                else:
                    color = GREEN if site in selected else DIM
                    default_mark = f" {DIM}[suggested]{RESET}" if site in DEFAULT_SELECTED else ""
                    print(f"  {color}{i+1:2}. {checked} {site}{default_mark}{RESET}")

            # Show selected summary
            if selected:
                print(f"\n{DIM}Selected ({len(selected)}): {', '.join(sorted(selected)[:5])}{' …' if len(selected)>5 else ''}{RESET}")
            else:
                print(f"\n{DIM}Selected: (none){RESET}")
            custom_only = [s for s in selected if s not in SUGGESTED_SITES]
            if custom_only:
                print(f"{DIM}Custom: {', '.join(sorted(custom_only))}{RESET}")
            print(f"\n{DIM}Highlighted: {SUGGESTED_SITES[idx]}  [{ '☑' if SUGGESTED_SITES[idx] in selected else '☐' }] — press Space to toggle{RESET}")

            key = read_key()
            if key == "up":
                idx = (idx - 1) % len(SUGGESTED_SITES)
            elif key == "down":
                idx = (idx + 1) % len(SUGGESTED_SITES)
            elif key == "space":
                site = SUGGESTED_SITES[idx]
                if site in selected:
                    selected.remove(site)
                else:
                    selected.add(site)
            elif key == "enter":
                return sorted(selected)
            elif key in ("q", "esc"):
                return None
            elif key == "a":
                selected = set(SUGGESTED_SITES)
            elif key == "n":
                selected = set()
            elif key == "c":
                # Need to restore terminal for input()
                sys.stdout.write(SHOW_CURSOR)
                sys.stdout.flush()
                _clear()
                print(BANNER)
                print(f"{BOLD}{title} — custom domain{RESET}")
                print(f"{DIM}{'─'*50}{RESET}")
                try:
                    custom = input("  Enter custom domain (e.g. youtube.com, or comma-separated): ").strip()
                except (EOFError, KeyboardInterrupt):
                    custom = ""
                sys.stdout.write(HIDE_CURSOR)
                sys.stdout.flush()
                if not custom:
                    continue
                for part in custom.replace(" ", "").split(","):
                    if not part:
                        continue
                    d = normalize_domain(part)
                    if not d or "." not in d:
                        print(f"  {RED}✗ Invalid domain: {part}{RESET}")
                        time.sleep(0.7)
                        continue
                    selected.add(d)
            elif key.isdigit():
                # Allow quick toggle via number keys 1-9 (first 9 sites)
                try:
                    n = int(key)
                    # For 1-9, map to 1-9; for multi-digit not needed in raw mode (single char)
                    if 1 <= n <= len(SUGGESTED_SITES):
                        site = SUGGESTED_SITES[n - 1]
                        if site in selected:
                            selected.remove(site)
                        else:
                            selected.add(site)
                except ValueError:
                    pass
    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()


def _select_sites_interactive(current: set[str] | None = None, title: str = "Select sites to block") -> list[str] | None:
    """Dispatch to arrow or legacy based on TTY."""
    if is_interactive():
        try:
            return _arrow_select_sites(current, title)
        except Exception as e:
            # Fallback on any error (e.g., termios not available)
            print(f"{DIM}(arrow input failed: {e}, falling back to keyboard){RESET}")
            time.sleep(0.5)
            return _select_sites_interactive_legacy(current, title)
    else:
        return _select_sites_interactive_legacy(current, title)


def _setup_flow() -> bool:
    """Run full setup. Returns True if completed."""
    _header("Setup — choose sites & set password")
    print("We block via /etc/hosts → works in Chrome, Firefox, etc.")
    print(f"System-wide. Needs your sudo password at the end to apply.")
    print(f"Blocks re-applied on every boot (systemd).")
    print()

    chosen = _select_sites_interactive(None, "Setup — select sites to block")
    if chosen is None:
        print(f"\n{DIM}Setup cancelled.{RESET}")
        time.sleep(0.8)
        return False

    if not chosen:
        print(f"\n{YELLOW}No sites selected. You can add later from the menu.{RESET}")
    else:
        print(f"\n{GREEN}Will block: {', '.join(chosen)}{RESET}")

    print(f"\n{BOLD}Set a password to protect unblocking{RESET}")
    print(f"  Must be at least {YELLOW}{MIN_PASSWORD_LENGTH} characters{RESET}. You will need it to unblock/disable.")
    print(f"  {DIM}Tip: use a long phrase like 'correct-horse-battery-staple-keep-focused-2025'{RESET}")
    try:
        pw = prompt_new_password()
    except (EOFError, KeyboardInterrupt):
        print(f"\n{DIM}Setup cancelled.{RESET}")
        return False

    salt, h = hash_password(pw)
    cfg = default_config(h, salt, chosen)
    try:
        save_config(cfg)
    except OSError as e:
        print(f"{RED}✗ Failed to save config {config_location()}: {e}{RESET}")
        _pause()
        return False

    _header("Applying blocks...")
    try:
        apply_block(cfg["blocked_sites"], enabled=True)
        print(f"{GREEN}✓ Blocked {len(cfg['blocked_sites'])} site(s){RESET}")
        if cfg["blocked_sites"]:
            print(f"  {DIM}→ {len(cfg['blocked_sites'])*2} hosts entries (bare + www.){RESET}")
    except PermissionError as e:
        print(f"{RED}✗ {e}{RESET}")
        print(f"{YELLOW}  Try running: sudo keep-focused (or run this app with sudo){RESET}")
        _pause()
        return False
    except Exception as e:
        print(f"{RED}✗ Failed to write hosts: {e}{RESET}")
        _pause()
        return False

    print(f"\n{DIM}Enabling autostart on boot...{RESET}")
    if install_service():
        print(f"{GREEN}✓ Autostart enabled — blocks re-applied on every boot.{RESET}")
    else:
        print(f"{YELLOW}  ! Could not enable autostart (systemd not found or permission).{RESET}")
        print(f"    Blocks are active now but may need re-apply after reboot.")
        print(f"    You can enable later from the menu (needs sudo).")

    print(f"\n{GREEN}{BOLD}Done!{RESET} Use the menu to manage blocks. To unblock you will need your password.")
    _pause("Press ENTER to go to main menu...")
    return True


def _view_blocked(cfg: dict) -> None:
    _header("Blocked sites")
    _status_line(cfg)
    sites = sorted(cfg.get("blocked_sites", []))
    if not sites:
        print(f"{DIM}(no sites blocked){RESET}")
    else:
        for s in sites:
            print(f"  {CYAN}•{RESET} {s}  {DIM}(also www.{s}){RESET}")
        print(f"\n{DIM}Total: {len(sites)} sites → {len(sites)*2} hosts entries{RESET}")
        active = get_blocked_from_hosts()
        if active:
            print(f"{DIM}Hosts currently has {len(active)} entries.{RESET}")
    _pause()


def _block_more(cfg: dict) -> dict:
    _header("Block more sites")
    _status_line(cfg)
    current = set(cfg.get("blocked_sites", []))
    chosen = _select_sites_interactive(current, "Block — select sites (current checked)")
    if chosen is None:
        return cfg
    current_sorted = sorted(current)
    if sorted(chosen) == current_sorted:
        print(f"\n{DIM}No changes.{RESET}")
        _pause()
        return cfg
    new_sites = sorted(set(chosen))
    if not _verify_or_exit(cfg):
        return cfg
    cfg["blocked_sites"] = new_sites
    cfg["enabled"] = True
    try:
        save_config(cfg)
        if new_sites:
            apply_block(new_sites, enabled=True)
            print(f"\n{GREEN}✓ Now blocking {len(new_sites)} site(s).{RESET}")
        else:
            clear_block()
            print(f"\n{GREEN}✓ No sites blocked — cleared.{RESET}")
    except PermissionError as e:
        print(f"{RED}✗ {e}{RESET}")
    except Exception as e:
        print(f"{RED}✗ Failed: {e}{RESET}")
    _pause()
    return cfg


def _unblock_flow(cfg: dict) -> dict:
    _header("Unblock sites")
    _status_line(cfg)
    sites = sorted(cfg.get("blocked_sites", []))
    if not sites:
        print(f"{DIM}(no sites to unblock){RESET}")
        _pause()
        return cfg
    print("Select sites to KEEP blocked (uncheck to unblock):\n")
    chosen = _select_sites_interactive(set(sites), "Unblock — uncheck sites to unblock")
    if chosen is None:
        return cfg
    if sorted(chosen) == sites:
        print(f"\n{DIM}No changes.{RESET}")
        _pause()
        return cfg
    if not _verify_or_exit(cfg):
        return cfg
    cfg["blocked_sites"] = sorted(chosen)
    try:
        save_config(cfg)
        if chosen:
            apply_block(chosen, enabled=cfg.get("enabled", True))
            removed = set(sites) - set(chosen)
            print(f"\n{GREEN}✓ Unblocked: {', '.join(sorted(removed))}{RESET}")
            print(f"  Still blocking {len(chosen)} site(s).")
        else:
            clear_block()
            print(f"\n{GREEN}✓ All sites unblocked.{RESET}")
    except PermissionError as e:
        print(f"{RED}✗ {e}{RESET}")
    except Exception as e:
        print(f"{RED}✗ Failed: {e}{RESET}")
    _pause()
    return cfg


def _toggle_enable(cfg: dict) -> dict:
    _header("Toggle blocking")
    _status_line(cfg)
    enabled = cfg.get("enabled", True)
    active = is_block_active()
    print(f"Currently: {'🟢 ENABLED' if enabled and active else '🔴 DISABLED'}\n")
    if enabled:
        print("This will {0} all blocking (make sites reachable).".format(f"{YELLOW}disable{RESET}"))
        print("Requires password.")
        choice = input("\nDisable blocking? [y/N]: ").strip().lower()
        if choice not in ("y", "yes"):
            print("Cancelled.")
            _pause()
            return cfg
        if not _verify_or_exit(cfg):
            return cfg
        cfg["enabled"] = False
        save_config(cfg)
        try:
            clear_block()
            print(f"{GREEN}✓ Blocking disabled. All sites now reachable.{RESET}")
        except PermissionError as e:
            print(f"{RED}✗ {e}{RESET}")
    else:
        print("This will re-enable blocking.")
        print("Requires password.")
        choice = input("\nEnable blocking? [Y/n]: ").strip().lower()
        if choice in ("n", "no"):
            print("Cancelled.")
            _pause()
            return cfg
        if not _verify_or_exit(cfg):
            return cfg
        cfg["enabled"] = True
        save_config(cfg)
        try:
            apply_block(cfg.get("blocked_sites", []), enabled=True)
            print(f"{GREEN}✓ Blocking enabled ({len(cfg.get('blocked_sites', []))} sites).{RESET}")
        except PermissionError as e:
            print(f"{RED}✗ {e}{RESET}")
    _pause()
    return cfg


def _change_password(cfg: dict) -> dict:
    _header("Change password")
    print(f"Current password protects unblocking. Must stay {MIN_PASSWORD_LENGTH}+ chars.")
    if not _verify_or_exit(cfg):
        return cfg
    print(f"\n{BOLD}Set new password{RESET}")
    try:
        pw = prompt_new_password()
    except (EOFError, KeyboardInterrupt):
        print("Cancelled.")
        _pause()
        return cfg
    salt, h = hash_password(pw)
    cfg["salt"] = salt
    cfg["password_hash"] = h
    save_config(cfg)
    print(f"{GREEN}✓ Password changed.{RESET}")
    _pause()
    return cfg


def _uninstall_flow(cfg: dict | None) -> bool:
    _header("Uninstall — remove all blocks")
    if cfg:
        print(f"{RED}This will remove all blocks, autostart, and config.{RESET}")
        print("Requires password.")
        if not _verify_or_exit(cfg):
            return False
    else:
        print("No config found — will still clean hosts and services if any.")
        choice = input("Uninstall anyway? [y/N]: ").strip().lower()
        if choice not in ("y", "yes"):
            return False

    print("\nCleaning...")
    try:
        clear_block()
        print(f"{GREEN}✓ Hosts cleaned.{RESET}")
    except PermissionError as e:
        print(f"{RED}✗ Hosts: {e} — try with sudo{RESET}")
    except Exception as e:
        print(f"{RED}✗ Hosts: {e}{RESET}")

    if uninstall_service():
        print(f"{GREEN}✓ Autostart removed.{RESET}")
    else:
        print(f"{YELLOW}  ! Could not remove service fully.{RESET}")

    from .config import _all_config_paths

    for p in _all_config_paths():
        try:
            if p.exists():
                # Unlock if immutable (best-effort) before delete
                try:
                    from .lock import unlock_file

                    unlock_file(p)
                except Exception:
                    pass
                p.unlink()
                try:
                    p.parent.rmdir()
                except OSError:
                    pass
                print(f"{GREEN}✓ Removed {p}{RESET}")
        except PermissionError:
            import shutil
            import subprocess

            # Try unlock via sudo before retry
            try:
                from .lock import unlock_file

                unlock_file(p)
                p.unlink()
                print(f"{GREEN}✓ Removed {p}{RESET}")
                continue
            except Exception:
                pass
            if shutil.which("sudo"):
                subprocess.run(["sudo", "rm", "-f", str(p)], check=False)
                print(f"{GREEN}✓ Removed {p} (via sudo){RESET}")
            else:
                print(f"{RED}✗ Permission denied removing {p}{RESET}")
        except Exception as e:
            print(f"{RED}✗ {p}: {e}{RESET}")

    print(f"\n{GREEN}Uninstalled.{RESET}")
    _pause()
    return True


def _update_flow() -> None:
    _header("Update — check for latest version")
    from . import __version__
    from .update import perform_update

    print(f"  Current version: {__version__}")
    print(f"{DIM}Checking GitHub for updates...{RESET}\n")
    # Use perform_update with check_only first to show version
    rc = perform_update(check_only=False, force=False)
    if rc == 0:
        print(f"\n{DIM}Done. Restart keep-focused if it was updated.{RESET}")
    else:
        print(f"\n{YELLOW}Update completed with warnings (see above).{RESET}")
    _pause()


# ---------------------------------------------------------------------------
# Arrow main menu
# ---------------------------------------------------------------------------
def _main_menu_legacy(cfg: dict | None) -> str:
    _header("Main menu")
    _status_line(cfg)
    if cfg is None:
        print(f"{BOLD}1{RESET}. Setup — choose sites & set password {YELLOW}(first run){RESET}")
        print(f"{BOLD}q{RESET}. Quit")
        print()
        try:
            choice = input(f"{BOLD}↳ Choose [1/q]: {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "quit"
        if choice in ("1", "s", "setup", ""):
            return "setup"
        if choice in ("q", "quit", "exit"):
            return "quit"
        return "setup" if choice == "" else "quit"

    print(f"{BOLD}1{RESET}. View blocked sites")
    print(f"{BOLD}2{RESET}. Block more sites (suggested + custom)")
    print(f"{BOLD}3{RESET}. Unblock sites")
    print(f"{BOLD}4{RESET}. Toggle enable/disable")
    print(f"{BOLD}5{RESET}. Change password")
    print(f"{BOLD}6{RESET}. Update (check & install latest)")
    print(f"{BOLD}7{RESET}. Uninstall (remove all)")
    print(f"{BOLD}q{RESET}. Quit")
    print(f"\n{DIM}Config: {config_location()}  |  autostart: {'on' if is_service_enabled() else 'off'}{RESET}")
    try:
        choice = input(f"\n{BOLD}↳ Choose [1-7/q]: {RESET}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "quit"
    mapping = {
        "1": "view",
        "2": "block",
        "3": "unblock",
        "4": "toggle",
        "5": "passwd",
        "6": "update",
        "7": "uninstall",
        "q": "quit",
        "quit": "quit",
        "exit": "quit",
    }
    return mapping.get(choice, "view" if choice == "" else "invalid")


def _arrow_main_menu(cfg: dict | None) -> str:
    if cfg is None:
        items = [("Setup — choose sites & set password", "setup"), ("Quit", "quit")]
    else:
        items = [
            ("View blocked sites", "view"),
            ("Block more sites (suggested + custom)", "block"),
            ("Unblock sites", "unblock"),
            ("Toggle enable/disable", "toggle"),
            ("Change password", "passwd"),
            ("Update (check & install latest)", "update"),
            ("Uninstall (remove all)", "uninstall"),
            ("Quit", "quit"),
        ]
    idx = 0
    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()
    try:
        while True:
            _header("Main menu")
            _status_line(cfg)
            for i, (label, _) in enumerate(items):
                if i == idx:
                    print(f"{REVERSE} › {label} {RESET}")
                else:
                    print(f"   {label}")
            if cfg is not None:
                print(f"\n{DIM}Config: {config_location()}  |  autostart: {'on' if is_service_enabled() else 'off'}{RESET}")
            print(f"\n{DIM}↑/↓ to move • Enter to select • q/Esc to quit{RESET}")

            key = read_key()
            if key == "up":
                idx = (idx - 1) % len(items)
            elif key == "down":
                idx = (idx + 1) % len(items)
            elif key == "enter":
                return items[idx][1]
            elif key in ("q", "esc"):
                return "quit"
            elif key in ("1", "2", "3", "4", "5", "6", "7", "8"):
                try:
                    n = int(key) - 1
                    if 0 <= n < len(items):
                        return items[n][1]
                except ValueError:
                    pass
    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()


def _main_menu(cfg: dict | None) -> str:
    if is_interactive():
        try:
            return _arrow_main_menu(cfg)
        except Exception as e:
            print(f"{DIM}(arrow menu failed: {e}, fallback){RESET}")
            time.sleep(0.3)
            return _main_menu_legacy(cfg)
    else:
        return _main_menu_legacy(cfg)


def run_tui() -> None:
    """Main TUI loop – like opencode. Handles Ctrl+C gracefully."""
    try:
        while True:
            cfg = load_config()
            action = _main_menu(cfg)

            if action == "quit":
                _clear()
                print(f"{DIM}Bye — stay focused!{RESET}")
                break
            if action == "invalid":
                print(f"{RED}Invalid choice.{RESET}")
                time.sleep(0.7)
                continue

            if action == "setup":
                _setup_flow()
                continue

            if cfg is None:
                print(f"{YELLOW}Not set up yet.{RESET}")
                time.sleep(0.8)
                continue

            if action == "view":
                _view_blocked(cfg)
            elif action == "block":
                _block_more(cfg)
            elif action == "unblock":
                _unblock_flow(cfg)
            elif action == "toggle":
                _toggle_enable(cfg)
            elif action == "passwd":
                _change_password(cfg)
            elif action == "update":
                _update_flow()
            elif action == "uninstall":
                if _uninstall_flow(cfg):
                    time.sleep(0.5)
                continue
    except KeyboardInterrupt:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()
        print(f"\n\n{DIM}Interrupted. Bye!{RESET}")
        sys.exit(0)
