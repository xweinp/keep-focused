"""Interactive CLI app (TUI) for keep-focused – like opencode/claude code.

Run `keep-focused` without args to launch this app.
Arrow navigation: Up/Down + Enter, Space to toggle — now powered by Rich.
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

# Try Rich for pretty rendering, fallback to plain ANSI
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.align import Align
    from rich.box import ROUNDED, HEAVY
    from rich import print as rprint

    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None  # type: ignore

# ANSI helpers – keep for fallback and for legacy tests
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


def _banner() -> str:
    from . import __version__

    return (
        f"{BOLD}{CYAN}\n"
        f"  _  __                       ___                                   _   _ \n"
        f" | |/ /  ___   ___   _ __    | __|  ___   __   _  _   ___  ___   __| | | |\n"
        f" | ' <  / -_) / -_) | '_ \\   | _|  / _ \\ / _| | || | (_-< / -_) / _` | |_|\n"
        f" |_|\\_\\ \\___| \\___| | .__/   |_|   \\___/ \\__|  \\_,_| /__/ \\___| \\__,_| (_)\n"
        f"                    |_|                                                   \n"
        f"                         🎯  keep-focused v{__version__}\n"
        f"{RESET}"
    )


BANNER = _banner()


def _pause(msg: str = "Press ENTER to continue...") -> None:
    try:
        if HAS_RICH and console:
            console.print(f"\n[dim]{msg}[/]", highlight=False)
            input()
        else:
            input(f"\n{DIM}{msg}{RESET}")
    except (EOFError, KeyboardInterrupt):
        print()


def _clear() -> None:
    if HAS_RICH and console and sys.stdout.isatty():
        console.clear()
    elif sys.stdout.isatty():
        sys.stdout.write(CLEAR)
        sys.stdout.flush()


def _header(title: str) -> None:
    _clear()
    if HAS_RICH and console:
        console.print(Panel(BANNER.strip(), box=ROUNDED, style="cyan", padding=(0, 1)))
        console.print(Panel(f"[bold]{title}[/]", box=HEAVY, style="bold", padding=(0, 1)))
    else:
        print(BANNER)
        print(f"{BOLD}{title}{RESET}")
        print(f"{DIM}{'─' * 50}{RESET}")


def _status_line(cfg: dict | None, show_config: bool = True) -> None:
    if HAS_RICH and console:
        if cfg is None:
            console.print(Panel("[yellow]⚙  Not set up yet[/]  → run Setup", style="yellow", box=ROUNDED))
            return
        enabled = cfg.get("enabled", True)
        blocked = cfg.get("blocked_sites", [])
        active = is_block_active()
        svc = is_service_enabled()
        loc = str(config_location())
        sites_left = f"{len(blocked)} blocked" if blocked else "0 blocked"
        sites_detail = f"({', '.join(sorted(blocked)[:3])}{'...' if len(blocked)>3 else ''})" if blocked else "(none)"
        state_detail = f"(hosts {'active' if active else 'inactive'}, autostart {'on' if svc else 'off'})"
        emoji = "🟢" if enabled and active else "🔴"
        pad_len = max(len(sites_left) + 4, 12)
        sites_padded = sites_left.ljust(pad_len)
        state_padded = emoji.ljust(pad_len)

        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("k", style="bold", no_wrap=True)
        table.add_column("v", style="white")
        table.add_column("d", style="dim")
        if show_config:
            table.add_row("Config:", loc, "")
        table.add_row("Sites:", f"[bold]{sites_padded}[/]", f"[dim]{sites_detail}[/]")
        table.add_row("State:", state_padded, f"[dim]{state_detail}[/]")
        console.print(Panel(table, box=ROUNDED, style="dim", padding=(0, 1)))
        console.print()
    else:
        if cfg is None:
            print(f"{YELLOW}⚙  Not set up yet{RESET}  → run Setup\n")
            return
        enabled = cfg.get("enabled", True)
        blocked = cfg.get("blocked_sites", [])
        active = is_block_active()
        svc = is_service_enabled()
        loc = config_location()
        if show_config:
            print(f" Config:  {DIM}{loc}{RESET}")
        sites_left = f"{len(blocked)} blocked" if blocked else "0 blocked"
        sites_detail = f"({', '.join(sorted(blocked)[:3])}{'...' if len(blocked)>3 else ''})" if blocked else "(none)"
        state_detail = f"(hosts {'active' if active else 'inactive'}, autostart {'on' if svc else 'off'})"
        emoji = "🟢" if enabled and active else "🔴"
        pad_len = max(len(sites_left) + 4, 12)
        sites_padded = sites_left.ljust(pad_len)
        state_padded = emoji.ljust(pad_len)
        print(f" Sites:   {BOLD}{sites_padded}{RESET} {DIM}{sites_detail}{RESET}")
        print(f" State:   {state_padded} {DIM}{state_detail}{RESET}")
        print()


def _verify_or_exit(cfg: dict) -> bool:
    try:
        pw = prompt_password("Enter password to authorize: ")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return False
    if not verify_password(pw, cfg["salt"], cfg["password_hash"]):
        if HAS_RICH and console:
            console.print("[red]✗ Wrong password.[/]")
        else:
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
        if HAS_RICH and console:
            console.print("[dim]Enter number to toggle, type custom domain to add, d=done q=cancel[/]\n")
        else:
            print(f"{DIM}Enter number to toggle, type custom domain to add, d=done q=cancel{RESET}\n")
        for i, site in enumerate(SUGGESTED_SITES, 1):
            checked = "☑" if site in selected else "☐"
            if HAS_RICH and console:
                color = "green" if site in selected else "dim"
                default_mark = " [dim][suggested][/]" if site in DEFAULT_SELECTED else ""
                console.print(f"  [cyan]{i:2}.[/] [{color}]{checked} {site}[/]{default_mark}")
            else:
                color = GREEN if site in selected else DIM
                default_mark = f" {DIM}[suggested]{RESET}" if site in DEFAULT_SELECTED else ""
                print(f"  {color}{i:2}. {checked} {site}{default_mark}{RESET}")
        customs = sorted(s for s in selected if s not in SUGGESTED_SITES)
        offset = len(SUGGESTED_SITES)
        for j, site in enumerate(customs, 1):
            if HAS_RICH and console:
                console.print(f"  [cyan]{offset+j:2}.[/] [green]☑ {site}[/] [dim][custom][/]")
            else:
                print(f"  {GREEN}{offset+j:2}. ☑ {site} {DIM}[custom]{RESET}")
        if HAS_RICH and console:
            console.print(f"  [dim]{offset+len(customs)+1:2}. ☐ [ Type custom domain and press Enter to add ][/]")
        else:
            print(f"  {DIM}{offset+len(customs)+1:2}. ☐ [ Type custom domain and press Enter to add ]{RESET}")
        if selected:
            if HAS_RICH and console:
                console.print(f"\n[dim]Selected: {', '.join(sorted(selected))}[/]")
            else:
                print(f"\n{DIM}Selected: {', '.join(sorted(selected))}{RESET}")
        else:
            if HAS_RICH and console:
                console.print("\n[dim]Selected: (none)[/]")
            else:
                print(f"\n{DIM}Selected: (none){RESET}")

        try:
            raw = input(f"\n{BOLD}↳{RESET} Enter number / domain / d/q: ").strip() if not HAS_RICH else input("\n↳ Enter number / domain / d/q: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        low = raw.lower()
        if low in ("d", "done", ""):
            break
        if low in ("q", "quit", "cancel"):
            return None
        parts = [p.strip() for p in raw.replace(" ", "").split(",") if p.strip()]
        any_handled = False
        for part in parts:
            try:
                idx = int(part)
                if 1 <= idx <= len(SUGGESTED_SITES):
                    site = SUGGESTED_SITES[idx - 1]
                    if site in selected:
                        selected.remove(site)
                    else:
                        selected.add(site)
                    any_handled = True
                    continue
                if offset + 1 <= idx <= offset + len(customs):
                    site = customs[idx - offset - 1]
                    if site in selected:
                        selected.remove(site)
                    else:
                        selected.add(site)
                    any_handled = True
                    continue
                if idx == offset + len(customs) + 1:
                    try:
                        custom = input("  Enter custom domain: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        continue
                    if not custom:
                        continue
                    d = normalize_domain(custom)
                    if not d or "." not in d:
                        if HAS_RICH and console:
                            console.print(f"  [red]✗ Invalid domain: {custom}[/]")
                        else:
                            print(f"  {RED}✗ Invalid domain: {custom}{RESET}")
                        time.sleep(0.7)
                        continue
                    selected.add(d)
                    any_handled = True
                    continue
                if HAS_RICH and console:
                    console.print(f"  [red]✗ Out of range: {part}[/]")
                else:
                    print(f"  {RED}✗ Out of range: {part}{RESET}")
                time.sleep(0.7)
                continue
            except ValueError:
                pass
            d = normalize_domain(part)
            if d and "." in d:
                if d in selected:
                    selected.remove(d)
                else:
                    selected.add(d)
                any_handled = True
            else:
                if HAS_RICH and console:
                    console.print(f"  [red]✗ Invalid: {part}[/]")
                else:
                    print(f"  {RED}✗ Invalid: {part}{RESET}")
                time.sleep(0.7)
        if any_handled:
            continue

    return sorted(selected)


# ---------------------------------------------------------------------------
# Arrow-based site selector — now with Rich panels
# ---------------------------------------------------------------------------
def _arrow_select_sites(current: set[str] | None, title: str) -> list[str] | None:
    selected: set[str] = set(current) if current is not None else set(DEFAULT_SELECTED)
    idx = 0
    if HAS_RICH and console:
        # Use Rich for rendering but keep read_key for navigation (so tests still mock it)
        pass
    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()
    try:
        while True:
            customs = sorted(s for s in selected if s not in SUGGESTED_SITES)

            def _all_items():
                lst = list(SUGGESTED_SITES)
                lst.extend(customs)
                lst.append("__ADD_CUSTOM__")
                return lst

            all_items = _all_items()
            n_items = len(all_items)
            idx = idx % n_items

            _header(title)
            if HAS_RICH and console:
                console.print("[dim]↑/↓ move • Space toggle • Enter done • q/Esc cancel[/]\n")
            else:
                print(f"{DIM}↑/↓ move • Space toggle • Enter done • q/Esc cancel{RESET}\n")

            for i, site in enumerate(all_items):
                is_add = site == "__ADD_CUSTOM__"
                if is_add:
                    label = "[ Type custom domain and press Enter to add ]"
                    if i == idx:
                        if HAS_RICH and console:
                            console.print(Panel(f" {i+1:2}. ☐ {label} ", style="reverse", box=ROUNDED))
                        else:
                            print(f"{REVERSE}  {i+1:2}. ☐ {label}  {RESET}")
                    else:
                        if HAS_RICH and console:
                            console.print(f"  [dim]{i+1:2}. ☐ {label}[/]")
                        else:
                            print(f"  {DIM}{i+1:2}. ☐ {label}{RESET}")
                    continue
                checked = "☑" if site in selected else "☐"
                if site in SUGGESTED_SITES:
                    is_suggested = True
                    default_mark = " [dim][suggested][/]" if site in DEFAULT_SELECTED else ""
                    plain_mark = f" {DIM}[suggested]{RESET}" if site in DEFAULT_SELECTED else ""
                else:
                    is_suggested = False
                    default_mark = " [dim][custom][/]"
                    plain_mark = f" {DIM}[custom]{RESET}"
                if i == idx:
                    if HAS_RICH and console:
                        console.print(Panel(f" {i+1:2}. {checked} {site}{default_mark} ", style="reverse", box=ROUNDED))
                    else:
                        dm = f" {DIM}[suggested]{RESET}{REVERSE}" if is_suggested and site in DEFAULT_SELECTED else (f" {DIM}[custom]{RESET}{REVERSE}" if not is_suggested else "")
                        print(f"{REVERSE}  {i+1:2}. {checked} {site}{dm}  {RESET}")
                else:
                    if HAS_RICH and console:
                        color = "green" if site in selected else "dim"
                        console.print(f"  [cyan]{i+1:2}.[/] [{color}]{checked} {site}[/]{default_mark}")
                    else:
                        color = GREEN if site in selected else DIM
                        dm2 = f" {DIM}[suggested]{RESET}" if is_suggested and site in DEFAULT_SELECTED else (f" {DIM}[custom]{RESET}" if not is_suggested else "")
                        print(f"  {color}{i+1:2}. {checked} {site}{dm2}{RESET}")

            if selected:
                if HAS_RICH and console:
                    console.print(f"\n[dim]Selected ({len(selected)}): {', '.join(sorted(selected)[:5])}{' …' if len(selected)>5 else ''}[/]")
                else:
                    print(f"\n{DIM}Selected ({len(selected)}): {', '.join(sorted(selected)[:5])}{' …' if len(selected)>5 else ''}{RESET}")
            else:
                if HAS_RICH and console:
                    console.print("\n[dim]Selected: (none)[/]")
                else:
                    print(f"\n{DIM}Selected: (none){RESET}")
            cur = all_items[idx]
            if cur == "__ADD_CUSTOM__":
                if HAS_RICH and console:
                    console.print("\n[dim]Highlighted: [Add custom] — press Enter to type[/]")
                else:
                    print(f"\n{DIM}Highlighted: [Add custom] — press Enter to type{RESET}")
            else:
                if HAS_RICH and console:
                    console.print(f"\n[dim]Highlighted: {cur}  [{'☑' if cur in selected else '☐'}] — press Space to toggle[/]")
                else:
                    print(f"\n{DIM}Highlighted: {cur}  [{ '☑' if cur in selected else '☐' }] — press Space to toggle{RESET}")

            key = read_key()
            if key == "up":
                idx = (idx - 1) % n_items
            elif key == "down":
                idx = (idx + 1) % n_items
            elif key == "space":
                if all_items[idx] == "__ADD_CUSTOM__":
                    key = "enter"
                else:
                    site = all_items[idx]
                    if site in selected:
                        selected.remove(site)
                    else:
                        selected.add(site)
                    continue
            if key == "enter":
                if all_items[idx] == "__ADD_CUSTOM__":
                    sys.stdout.write(SHOW_CURSOR)
                    sys.stdout.flush()
                    _clear()
                    if HAS_RICH and console:
                        console.print(Panel(BANNER.strip(), box=ROUNDED, style="cyan"))
                        console.print(Panel(f"[bold]{title} — add custom domain[/]", box=HEAVY, style="bold"))
                    else:
                        print(BANNER)
                        print(f"{BOLD}{title} — add custom domain{RESET}")
                        print(f"{DIM}{'─'*50}{RESET}")
                    try:
                        custom = input("  Enter custom domain (e.g. myfavouritegame.com): ").strip()
                    except (EOFError, KeyboardInterrupt):
                        custom = ""
                    sys.stdout.write(HIDE_CURSOR)
                    sys.stdout.flush()
                    if not custom:
                        continue
                    added = False
                    for part in custom.replace(" ", "").split(","):
                        if not part:
                            continue
                        d = normalize_domain(part)
                        if not d or "." not in d:
                            if HAS_RICH and console:
                                console.print(f"  [red]✗ Invalid domain: {part}[/]")
                            else:
                                print(f"  {RED}✗ Invalid domain: {part}{RESET}")
                            time.sleep(0.7)
                            continue
                        selected.add(d)
                        added = True
                    if added:
                        idx = len(SUGGESTED_SITES) + len([s for s in selected if s not in SUGGESTED_SITES])
                    continue
                else:
                    return sorted(selected)
            elif key in ("q", "esc"):
                return None
            elif key.isdigit():
                try:
                    n = int(key)
                    if 1 <= n <= n_items:
                        target = all_items[n - 1]
                        if target == "__ADD_CUSTOM__":
                            sys.stdout.write(SHOW_CURSOR)
                            sys.stdout.flush()
                            _clear()
                            if HAS_RICH and console:
                                console.print(Panel(BANNER.strip(), box=ROUNDED, style="cyan"))
                                console.print(Panel(f"[bold]{title} — add custom domain[/]", box=HEAVY, style="bold"))
                            else:
                                print(BANNER)
                                print(f"{BOLD}{title} — add custom domain{RESET}")
                                print(f"{DIM}{'─'*50}{RESET}")
                            try:
                                custom = input("  Enter custom domain: ").strip()
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
                                    if HAS_RICH and console:
                                        console.print(f"  [red]✗ Invalid domain: {part}[/]")
                                    else:
                                        print(f"  {RED}✗ Invalid domain: {part}{RESET}")
                                    time.sleep(0.7)
                                    continue
                                selected.add(d)
                        else:
                            if target in selected:
                                selected.remove(target)
                            else:
                                selected.add(target)
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
            if HAS_RICH and console:
                console.print(f"[dim](arrow input failed: {e}, falling back to keyboard)[/]")
            else:
                print(f"{DIM}(arrow input failed: {e}, falling back to keyboard){RESET}")
            time.sleep(0.5)
            return _select_sites_interactive_legacy(current, title)
    else:
        return _select_sites_interactive_legacy(current, title)


def _setup_flow() -> bool:
    """Run full setup. Returns True if completed."""
    _header("Setup — choose sites & set password")
    if HAS_RICH and console:
        console.print("[dim]We block via /etc/hosts → works in Chrome, Firefox, etc.[/]")
        console.print("[dim]System-wide. Needs your sudo password at the end to apply.[/]")
        console.print("[dim]Blocks re-applied on every boot (systemd).[/]")
    else:
        print("We block via /etc/hosts → works in Chrome, Firefox, etc.")
        print(f"System-wide. Needs your sudo password at the end to apply.")
        print(f"Blocks re-applied on every boot (systemd).")
    print()

    chosen = _select_sites_interactive(None, "Setup — select sites to block")
    if chosen is None:
        if HAS_RICH and console:
            console.print("\n[dim]Setup cancelled.[/]")
        else:
            print(f"\n{DIM}Setup cancelled.{RESET}")
        time.sleep(0.8)
        return False

    if not chosen:
        if HAS_RICH and console:
            console.print("\n[yellow]No sites selected. You can add later from the menu.[/]")
        else:
            print(f"\n{YELLOW}No sites selected. You can add later from the menu.{RESET}")
    else:
        if HAS_RICH and console:
            console.print(f"\n[green]Will block: {', '.join(chosen)}[/]")
        else:
            print(f"\n{GREEN}Will block: {', '.join(chosen)}{RESET}")

    if HAS_RICH and console:
        console.print(f"\n[bold]Set a password to protect unblocking[/]")
        console.print(f"  Must be at least [yellow]{MIN_PASSWORD_LENGTH} characters[/]. You will need it to unblock/disable.")
        console.print(f"  [dim]Tip: use a long phrase like 'correct-horse-battery-staple-keep-focused-2025'[/]")
    else:
        print(f"\n{BOLD}Set a password to protect unblocking{RESET}")
        print(f"  Must be at least {YELLOW}{MIN_PASSWORD_LENGTH} characters{RESET}. You will need it to unblock/disable.")
        print(f"  {DIM}Tip: use a long phrase like 'correct-horse-battery-staple-keep-focused-2025'{RESET}")
    try:
        pw = prompt_new_password()
    except (EOFError, KeyboardInterrupt):
        if HAS_RICH and console:
            console.print("\n[dim]Setup cancelled.[/]")
        else:
            print(f"\n{DIM}Setup cancelled.{RESET}")
        return False

    salt, h = hash_password(pw)
    cfg = default_config(h, salt, chosen)
    try:
        save_config(cfg)
    except OSError as e:
        if HAS_RICH and console:
            console.print(f"[red]✗ Failed to save config {config_location()}: {e}[/]")
        else:
            print(f"{RED}✗ Failed to save config {config_location()}: {e}{RESET}")
        _pause()
        return False

    _header("Applying blocks...")
    try:
        apply_block(cfg["blocked_sites"], enabled=True)
        if HAS_RICH and console:
            console.print(f"[green]✓ Blocked {len(cfg['blocked_sites'])} site(s)[/]")
            if cfg["blocked_sites"]:
                console.print(f"  [dim]→ {len(cfg['blocked_sites'])*2} hosts entries (bare + www.)[/]")
        else:
            print(f"{GREEN}✓ Blocked {len(cfg['blocked_sites'])} site(s){RESET}")
            if cfg["blocked_sites"]:
                print(f"  {DIM}→ {len(cfg['blocked_sites'])*2} hosts entries (bare + www.){RESET}")
    except PermissionError as e:
        if HAS_RICH and console:
            console.print(f"[red]✗ {e}[/]")
            console.print("[yellow]  Try running: sudo keep-focused (or run this app with sudo)[/]")
        else:
            print(f"{RED}✗ {e}{RESET}")
            print(f"{YELLOW}  Try running: sudo keep-focused (or run this app with sudo){RESET}")
        _pause()
        return False
    except Exception as e:
        if HAS_RICH and console:
            console.print(f"[red]✗ Failed to write hosts: {e}[/]")
        else:
            print(f"{RED}✗ Failed to write hosts: {e}{RESET}")
        _pause()
        return False

    if HAS_RICH and console:
        console.print("\n[dim]Enabling autostart on boot...[/]")
    else:
        print(f"\n{DIM}Enabling autostart on boot...{RESET}")
    if install_service():
        if HAS_RICH and console:
            console.print("[green]✓ Autostart enabled — blocks re-applied on every boot.[/]")
        else:
            print(f"{GREEN}✓ Autostart enabled — blocks re-applied on every boot.{RESET}")
    else:
        if HAS_RICH and console:
            console.print("[yellow]  ! Could not enable autostart (systemd not found or permission).[/]")
            console.print("    Blocks are active now but may need re-apply after reboot.")
            console.print("    You can enable later from the menu (needs sudo).")
        else:
            print(f"{YELLOW}  ! Could not enable autostart (systemd not found or permission).{RESET}")
            print(f"    Blocks are active now but may need re-apply after reboot.")
            print(f"    You can enable later from the menu (needs sudo).")

    if HAS_RICH and console:
        console.print("\n[green bold]Done![/] Use the menu to manage blocks. To unblock you will need your password.")
    else:
        print(f"\n{GREEN}{BOLD}Done!{RESET} Use the menu to manage blocks. To unblock you will need your password.")
    _pause("Press ENTER to go to main menu...")
    return True


def _view_blocked(cfg: dict) -> None:
    _header("Blocked sites")
    _status_line(cfg)
    sites = sorted(cfg.get("blocked_sites", []))
    if not sites:
        if HAS_RICH and console:
            console.print("[dim](no sites blocked)[/]")
        else:
            print(f"{DIM}(no sites blocked){RESET}")
    else:
        for s in sites:
            if HAS_RICH and console:
                console.print(f"  [cyan]•[/] {s}  [dim](also www.{s})[/]")
            else:
                print(f"  {CYAN}•{RESET} {s}  {DIM}(also www.{s}){RESET}")
        if HAS_RICH and console:
            console.print(f"\n[dim]Total: {len(sites)} sites → {len(sites)*2} hosts entries[/]")
            active = get_blocked_from_hosts()
            if active:
                console.print(f"[dim]Hosts currently has {len(active)} entries.[/]")
        else:
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
        if HAS_RICH and console:
            console.print("\n[dim]No changes.[/]")
        else:
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
            if HAS_RICH and console:
                console.print(f"\n[green]✓ Now blocking {len(new_sites)} site(s).[/]")
            else:
                print(f"\n{GREEN}✓ Now blocking {len(new_sites)} site(s).{RESET}")
        else:
            clear_block()
            if HAS_RICH and console:
                console.print("\n[green]✓ No sites blocked — cleared.[/]")
            else:
                print(f"\n{GREEN}✓ No sites blocked — cleared.{RESET}")
    except PermissionError as e:
        if HAS_RICH and console:
            console.print(f"[red]✗ {e}[/]")
        else:
            print(f"{RED}✗ {e}{RESET}")
    except Exception as e:
        if HAS_RICH and console:
            console.print(f"[red]✗ Failed: {e}[/]")
        else:
            print(f"{RED}✗ Failed: {e}{RESET}")
    _pause()
    return cfg


def _unblock_flow(cfg: dict) -> dict:
    _header("Unblock sites")
    _status_line(cfg)
    sites = sorted(cfg.get("blocked_sites", []))
    if not sites:
        if HAS_RICH and console:
            console.print("[dim](no sites to unblock)[/]")
        else:
            print(f"{DIM}(no sites to unblock){RESET}")
        _pause()
        return cfg
    if HAS_RICH and console:
        console.print("Select sites to KEEP blocked (uncheck to unblock):\n")
    else:
        print("Select sites to KEEP blocked (uncheck to unblock):\n")
    chosen = _select_sites_interactive(set(sites), "Unblock — uncheck sites to unblock")
    if chosen is None:
        return cfg
    if sorted(chosen) == sites:
        if HAS_RICH and console:
            console.print("\n[dim]No changes.[/]")
        else:
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
            if HAS_RICH and console:
                console.print(f"\n[green]✓ Unblocked: {', '.join(sorted(removed))}[/]")
                console.print(f"  Still blocking {len(chosen)} site(s).")
            else:
                print(f"\n{GREEN}✓ Unblocked: {', '.join(sorted(removed))}{RESET}")
                print(f"  Still blocking {len(chosen)} site(s).")
        else:
            clear_block()
            if HAS_RICH and console:
                console.print("\n[green]✓ All sites unblocked.[/]")
            else:
                print(f"\n{GREEN}✓ All sites unblocked.{RESET}")
    except PermissionError as e:
        if HAS_RICH and console:
            console.print(f"[red]✗ {e}[/]")
        else:
            print(f"{RED}✗ {e}{RESET}")
    except Exception as e:
        if HAS_RICH and console:
            console.print(f"[red]✗ Failed: {e}[/]")
        else:
            print(f"{RED}✗ Failed: {e}{RESET}")
    _pause()
    return cfg


def _toggle_enable(cfg: dict) -> dict:
    _header("Toggle blocking")
    _status_line(cfg)
    enabled = cfg.get("enabled", True)
    active = is_block_active()
    if HAS_RICH and console:
        console.print(f"Currently: {'[green]🟢 ENABLED[/]' if enabled and active else '[red]🔴 DISABLED[/]'}\n")
    else:
        print(f"Currently: {'🟢 ENABLED' if enabled and active else '🔴 DISABLED'}\n")
    if enabled:
        if HAS_RICH and console:
            console.print("This will [yellow]disable[/] all blocking (make sites reachable).")
            console.print("Requires password.")
        else:
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
            if HAS_RICH and console:
                console.print("[green]✓ Blocking disabled. All sites now reachable.[/]")
            else:
                print(f"{GREEN}✓ Blocking disabled. All sites now reachable.{RESET}")
        except PermissionError as e:
            if HAS_RICH and console:
                console.print(f"[red]✗ {e}[/]")
            else:
                print(f"{RED}✗ {e}{RESET}")
    else:
        if HAS_RICH and console:
            console.print("This will re-enable blocking.")
            console.print("Requires password.")
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
            if HAS_RICH and console:
                console.print(f"[green]✓ Blocking enabled ({len(cfg.get('blocked_sites', []))} sites).[/]")
            else:
                print(f"{GREEN}✓ Blocking enabled ({len(cfg.get('blocked_sites', []))} sites).{RESET}")
        except PermissionError as e:
            if HAS_RICH and console:
                console.print(f"[red]✗ {e}[/]")
            else:
                print(f"{RED}✗ {e}{RESET}")
    _pause()
    return cfg


def _change_password(cfg: dict) -> dict:
    _header("Change password")
    if HAS_RICH and console:
        console.print(f"Current password protects unblocking. Must stay [cyan]{MIN_PASSWORD_LENGTH}+ chars[/].")
    else:
        print(f"Current password protects unblocking. Must stay {MIN_PASSWORD_LENGTH}+ chars.")
    if not _verify_or_exit(cfg):
        return cfg
    if HAS_RICH and console:
        console.print("\n[bold]Set new password[/]")
    else:
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
    if HAS_RICH and console:
        console.print("[green]✓ Password changed.[/]")
    else:
        print(f"{GREEN}✓ Password changed.{RESET}")
    _pause()
    return cfg


def _uninstall_flow(cfg: dict | None) -> bool:
    _header("Uninstall — remove all blocks")
    if cfg:
        if HAS_RICH and console:
            console.print("[red]This will remove all blocks, autostart, and config.[/]")
            console.print("Requires password.")
        else:
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
        if HAS_RICH and console:
            console.print("[green]✓ Hosts cleaned.[/]")
        else:
            print(f"{GREEN}✓ Hosts cleaned.{RESET}")
    except PermissionError as e:
        if HAS_RICH and console:
            console.print(f"[red]✗ Hosts: {e} — try with sudo[/]")
        else:
            print(f"{RED}✗ Hosts: {e} — try with sudo{RESET}")
    except Exception as e:
        if HAS_RICH and console:
            console.print(f"[red]✗ Hosts: {e}[/]")
        else:
            print(f"{RED}✗ Hosts: {e}{RESET}")

    if uninstall_service():
        if HAS_RICH and console:
            console.print("[green]✓ Autostart removed.[/]")
        else:
            print(f"{GREEN}✓ Autostart removed.{RESET}")
    else:
        if HAS_RICH and console:
            console.print("[yellow]  ! Could not remove service fully.[/]")
        else:
            print(f"{YELLOW}  ! Could not remove service fully.{RESET}")

    from .config import _all_config_paths

    for p in _all_config_paths():
        try:
            if p.exists():
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
                if HAS_RICH and console:
                    console.print(f"[green]✓ Removed {p}[/]")
                else:
                    print(f"{GREEN}✓ Removed {p}{RESET}")
        except PermissionError:
            import shutil
            import subprocess

            try:
                from .lock import unlock_file

                unlock_file(p)
                p.unlink()
                if HAS_RICH and console:
                    console.print(f"[green]✓ Removed {p}[/]")
                else:
                    print(f"{GREEN}✓ Removed {p}{RESET}")
                continue
            except Exception:
                pass
            if shutil.which("sudo"):
                subprocess.run(["sudo", "rm", "-f", str(p)], check=False)
                if HAS_RICH and console:
                    console.print(f"[green]✓ Removed {p} (via sudo)[/]")
                else:
                    print(f"{GREEN}✓ Removed {p} (via sudo){RESET}")
            else:
                if HAS_RICH and console:
                    console.print(f"[red]✗ Permission denied removing {p}[/]")
                else:
                    print(f"{RED}✗ Permission denied removing {p}{RESET}")
        except Exception as e:
            if HAS_RICH and console:
                console.print(f"[red]✗ {p}: {e}[/]")
            else:
                print(f"{RED}✗ {p}: {e}{RESET}")

    if HAS_RICH and console:
        console.print("\n[green]Uninstalled.[/]")
    else:
        print(f"\n{GREEN}Uninstalled.{RESET}")
    _pause()
    return True


def _update_flow() -> None:
    _header("Update — check for latest version")
    from . import __version__
    from .update import perform_update

    if HAS_RICH and console:
        console.print(f"  Current version: [cyan]{__version__}[/]")
        console.print(f"[dim]Checking GitHub for updates...[/]\n")
    else:
        print(f"  Current version: {__version__}")
        print(f"{DIM}Checking GitHub for updates...{RESET}\n")
    rc = perform_update(check_only=False, force=False)
    if rc == 0:
        if HAS_RICH and console:
            console.print("\n[dim]Done. Restart keep-focused if it was updated.[/]")
        else:
            print(f"\n{DIM}Done. Restart keep-focused if it was updated.{RESET}")
    else:
        if HAS_RICH and console:
            console.print("\n[yellow]Update completed with warnings (see above).[/]")
        else:
            print(f"\n{YELLOW}Update completed with warnings (see above).{RESET}")
    _pause()


# ---------------------------------------------------------------------------
# Arrow main menu — now with Rich panels
# ---------------------------------------------------------------------------
def _main_menu_legacy(cfg: dict | None) -> str:
    _clear()
    if HAS_RICH and console:
        console.print(Panel(BANNER.strip(), box=ROUNDED, style="cyan", padding=(0, 1)))
        console.print()
        _status_line(cfg, show_config=False)
        if cfg is None:
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("key", style="bold cyan", no_wrap=True)
            table.add_column("label", style="white")
            table.add_row("1", "Setup — choose sites & set password [yellow](first run)[/]")
            table.add_row("q", "Quit")
            console.print(Panel(table, title="[bold]Main Menu[/]", box=ROUNDED, style="dim"))
        else:
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("key", style="bold cyan", no_wrap=True)
            table.add_column("label", style="white")
            table.add_row("1", "View blocked sites")
            table.add_row("2", "Block any website (suggested + custom)")
            table.add_row("3", "Unblock sites")
            table.add_row("4", "Toggle enable/disable")
            table.add_row("5", "Change password")
            table.add_row("6", "Update (check & install latest)")
            table.add_row("7", "Uninstall (remove all)")
            table.add_row("q", "Quit")
            console.print(Panel(table, title="[bold]Main Menu[/]", box=ROUNDED, style="dim"))
        console.print("\n[dim]Choose [1-7/q]: [/]", end="")
    else:
        print(BANNER)
        print()
        _status_line(cfg, show_config=False)
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
        print(f"{BOLD}2{RESET}. Block any website (suggested + custom)")
        print(f"{BOLD}3{RESET}. Unblock sites")
        print(f"{BOLD}4{RESET}. Toggle enable/disable")
        print(f"{BOLD}5{RESET}. Change password")
        print(f"{BOLD}6{RESET}. Update (check & install latest)")
        print(f"{BOLD}7{RESET}. Uninstall (remove all)")
        print(f"{BOLD}q{RESET}. Quit")
    try:
        choice = input(f"\n{BOLD}↳ Choose [1-7/q]: {RESET}").strip().lower() if not HAS_RICH else input("\n↳ Choose [1-7/q]: ").strip().lower()
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
            ("Block any website (suggested + custom)", "block"),
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
            _clear()
            if HAS_RICH and console:
                console.print(Panel(BANNER.strip(), box=ROUNDED, style="cyan", padding=(0, 1)))
                console.print()
                _status_line(cfg, show_config=False)
                # Rich table for menu
                table = Table(box=ROUNDED, show_header=False, padding=(0, 1), border_style="dim")
                table.add_column("sel", no_wrap=True, width=2)
                table.add_column("label", style="white")
                for i, (label, _) in enumerate(items):
                    if i == idx:
                        table.add_row("›", f"[reverse] {label} [/]", style="bold cyan")
                    else:
                        table.add_row(" ", label)
                console.print(Panel(table, title="[bold]keep-focused[/]", box=HEAVY, padding=(0, 1)))
                console.print("\n[dim]↑/↓ to move • Enter to select • q/Esc to quit[/]")
            else:
                print(BANNER)
                print()
                _status_line(cfg, show_config=False)
                for i, (label, _) in enumerate(items):
                    if i == idx:
                        print(f"{REVERSE} › {label} {RESET}")
                    else:
                        print(f"   {label}")
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
            if HAS_RICH and console:
                console.print(f"[dim](arrow menu failed: {e}, fallback)[/]")
            else:
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
                if HAS_RICH and console:
                    console.print("[dim]Bye — stay focused![/]")
                else:
                    print(f"{DIM}Bye — stay focused!{RESET}")
                break
            if action == "invalid":
                if HAS_RICH and console:
                    console.print("[red]Invalid choice.[/]")
                else:
                    print(f"{RED}Invalid choice.{RESET}")
                time.sleep(0.7)
                continue

            if action == "setup":
                _setup_flow()
                continue

            if cfg is None:
                if HAS_RICH and console:
                    console.print("[yellow]Not set up yet.[/]")
                else:
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
        if HAS_RICH and console:
            console.print("\n\n[dim]Interrupted. Bye![/]")
        else:
            print(f"\n\n{DIM}Interrupted. Bye!{RESET}")
        sys.exit(0)
