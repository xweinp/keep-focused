"""CLI for keep-focused."""

import argparse
import os
import sys
from pathlib import Path

from . import DEFAULT_SELECTED, SUGGESTED_SITES, __version__
from .auth import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    prompt_new_password,
    prompt_password,
    verify_password,
)
from .config import default_config, load_config, save_config
from .hosts import apply_block, clear_block, get_blocked_from_hosts, is_block_active, normalize_domain
from .systemd import install_service, is_service_enabled, uninstall_service

BANNER = r"""
  keep-focused – stay productive
  Blocks distracting sites system-wide via /etc/hosts
  Works in Chrome, Firefox, and any browser
"""


def _require_setup() -> dict:
    cfg = load_config()
    if cfg is None:
        print("✗ Not set up yet. Run: keep-focused")
        sys.exit(1)
    return cfg


def _verify_auth(cfg: dict) -> None:
    """Prompt for password and verify; exit on failure."""
    # Allow bypass in tests via env
    pw = prompt_password("Enter password to authorize: ")
    if not verify_password(pw, cfg["salt"], cfg["password_hash"]):
        print("✗ Wrong password.")
        sys.exit(1)


def _print_suggested(selected: set[str] | None = None) -> None:
    print("\nSuggested sites to block:")
    for i, site in enumerate(SUGGESTED_SITES, 1):
        mark = "●" if selected and site in selected else "○"
        default_mark = " [default]" if site in DEFAULT_SELECTED else ""
        print(f"  {i:2}. {mark} {site}{default_mark}")


def cmd_setup(args) -> None:
    print(BANNER)
    existing = load_config()
    if existing and not args.force:
        print("Already set up. Use --force to re-run setup.")
        print("Current blocked sites:", ", ".join(existing.get("blocked_sites", [])) or "(none)")
        return

    # Interactive site selection
    print("Select sites to block during setup.")
    print("We suggest these popular distractors (defaults pre-selected):")
    _print_suggested(set(DEFAULT_SELECTED))

    print("\nEnter numbers comma-separated (e.g. 1,2,4,6)")
    print("  - Press ENTER to accept defaults: facebook.com, x.com, linkedin.com, spotify.com")
    print("  - Type 'a' for all suggested sites")
    print("  - Type 'n' for none (you can add later)")
    raw = input("\nYour selection [ENTER=defaults]: ").strip().lower()

    if raw == "":
        chosen = list(DEFAULT_SELECTED)
    elif raw == "a":
        chosen = list(SUGGESTED_SITES)
    elif raw == "n":
        chosen = []
    else:
        chosen = []
        for part in raw.replace(" ", "").split(","):
            if not part:
                continue
            try:
                idx = int(part)
                if 1 <= idx <= len(SUGGESTED_SITES):
                    chosen.append(SUGGESTED_SITES[idx - 1])
                else:
                    print(f"  ! Ignoring out-of-range: {part}")
            except ValueError:
                # allow direct domain entry
                chosen.append(part)
        # deduplicate while preserving order
        seen: set[str] = set()
        uniq: list[str] = []
        for c in chosen:
            nc = normalize_domain(c)
            if nc not in seen:
                seen.add(nc)
                uniq.append(nc)
        chosen = uniq

    # Allow adding custom sites
    if args.sites:
        for s in args.sites:
            nc = normalize_domain(s)
            if nc not in chosen:
                chosen.append(nc)

    if not chosen:
        print("\nNo sites selected. You can add sites later with: sudo keep-focused add <site>")
    else:
        print(f"\nWill block: {', '.join(chosen)}")

    # Password
    if args.password:
        pw = args.password
        if len(pw) < MIN_PASSWORD_LENGTH:
            print(f"✗ Password too short ({len(pw)} chars). Must be at least {MIN_PASSWORD_LENGTH}.")
            sys.exit(1)
    else:
        print(f"\nSet a password to protect unblocking (minimum {MIN_PASSWORD_LENGTH} characters).")
        print("You will need this password to unblock or disable protection.")
        pw = prompt_new_password()

    salt, h = hash_password(pw)
    cfg = default_config(h, salt, chosen)
    try:
        save_config(cfg)
    except PermissionError as e:
        print(f"✗ Permission denied writing config: {e}")
        print("  Try: keep-focused (will prompt for sudo if needed)")
        sys.exit(1)

    # Apply hosts blocking (uses sudo internally if needed)
    try:
        apply_block(cfg["blocked_sites"], enabled=cfg["enabled"])
    except PermissionError as e:
        print(f"✗ {e}")
        print("  Hint: your sudo password may be required. Try running: keep-focused")
        sys.exit(1)

    print(f"\n✓ Blocked {len(cfg['blocked_sites'])} site(s) (with www. variants → {len(cfg['blocked_sites'])*2} hosts entries).")
    print("  System-wide: Chrome, Firefox, etc. will now show connection errors for blocked sites.")

    # Systemd autostart
    print("\nEnabling autostart on boot (systemd)...")
    if install_service():
        print("✓ Autostart enabled (keep-focused.service). Blocks re-applied on every boot.")
    else:
        # Fallback hint
        print("  ! systemd not available or not root. Blocks are active now,")
        print("    but may need re-apply after reboot if hosts is reset.")
        print("    Ensure keep-focused is run at boot via your init system.")

    print("\nDone. Use 'keep-focused status' to verify.")
    print("To unblock, you will need your password.")


def cmd_status(args) -> None:
    cfg = load_config()
    if cfg is None:
        print("Not set up. Run: keep-focused")
        return
    print(BANNER)
    print(f"Enabled:        {'yes' if cfg.get('enabled') else 'no'}")
    print(f"Blocked sites:  {len(cfg.get('blocked_sites', []))}")
    for s in sorted(cfg.get("blocked_sites", [])):
        print(f"  - {s}  (also www.{s})")
    active = is_block_active()
    print(f"Hosts active:   {'yes' if active else 'no'}")
    print(f"Autostart:      {'enabled' if is_service_enabled() else 'disabled'}")
    hosts_domains = get_blocked_from_hosts()
    if hosts_domains:
        print(f"Hosts entries:  {len(hosts_domains)} domains")
    # Password info
    print(f"Password:       set (min {MIN_PASSWORD_LENGTH} chars, PBKDF2)")
    if not cfg.get("enabled") or not active:
        print("\n⚠ Blocking is currently DISABLED – sites are reachable.")
    else:
        print("\n✓ Blocking is ACTIVE – listed sites are unreachable in all browsers.")


def cmd_apply(args) -> None:
    """Internal: re-apply from config (used by systemd). No password needed."""
    cfg = load_config()
    if cfg is None:
        sys.exit(0)
    try:
        apply_block(cfg.get("blocked_sites", []), enabled=cfg.get("enabled", True))
    except PermissionError:
        print("apply: permission denied (need root)", file=sys.stderr)
        sys.exit(1)


def cmd_block(args) -> None:
    cfg = _require_setup()
    _verify_auth(cfg)
    if not args.sites:
        print("Usage: keep-focused block <site> [site ...]")
        sys.exit(1)
    added: list[str] = []
    for raw in args.sites:
        d = normalize_domain(raw)
        if not d or "." not in d:
            print(f"  ! Skipping invalid domain: {raw}")
            continue
        if d not in cfg["blocked_sites"]:
            cfg["blocked_sites"].append(d)
            added.append(d)
        else:
            print(f"  - Already blocked: {d}")
    if added:
        cfg["blocked_sites"] = sorted(set(cfg["blocked_sites"]))
        cfg["enabled"] = True
        save_config(cfg)
        apply_block(cfg["blocked_sites"], enabled=True)
        print(f"✓ Blocked: {', '.join(added)} (plus www. variants)")
    else:
        print("No new sites added.")


def cmd_unblock(args) -> None:
    cfg = _require_setup()
    _verify_auth(cfg)
    if not args.sites:
        print("Usage: keep-focused unblock <site> [site ...]")
        sys.exit(1)
    removed: list[str] = []
    for raw in args.sites:
        d = normalize_domain(raw)
        # Also handle www. input
        if d.startswith("www."):
            d = d[4:]
        if d in cfg["blocked_sites"]:
            cfg["blocked_sites"].remove(d)
            removed.append(d)
        else:
            print(f"  - Not blocked: {d}")
    if removed:
        save_config(cfg)
        if cfg["blocked_sites"] and cfg.get("enabled"):
            apply_block(cfg["blocked_sites"], enabled=True)
        elif not cfg["blocked_sites"]:
            clear_block()
        print(f"✓ Unblocked: {', '.join(removed)}")
        if not cfg["blocked_sites"]:
            print("  No sites left blocked.")
    else:
        print("No sites removed.")


def cmd_enable(args) -> None:
    cfg = _require_setup()
    _verify_auth(cfg)
    cfg["enabled"] = True
    save_config(cfg)
    if cfg["blocked_sites"]:
        apply_block(cfg["blocked_sites"], enabled=True)
        print(f"✓ Blocking enabled ({len(cfg['blocked_sites'])} sites).")
    else:
        print("No sites to block. Add some with: keep-focused block <site>")


def cmd_disable(args) -> None:
    cfg = _require_setup()
    _verify_auth(cfg)
    cfg["enabled"] = False
    save_config(cfg)
    clear_block()
    print("✓ Blocking disabled. All sites reachable. Enable again with: keep-focused enable")


def cmd_list(args) -> None:
    cfg = _require_setup()
    sites = cfg.get("blocked_sites", [])
    if not sites:
        print("(no sites blocked)")
        return
    for s in sorted(sites):
        print(s)


def cmd_passwd(args) -> None:
    cfg = _require_setup()
    _verify_auth(cfg)
    print(f"\nSet a new password (min {MIN_PASSWORD_LENGTH} chars).")
    if args.password:
        pw = args.password
        if len(pw) < MIN_PASSWORD_LENGTH:
            print(f"✗ Too short ({len(pw)}). Need {MIN_PASSWORD_LENGTH}.")
            sys.exit(1)
    else:
        pw = prompt_new_password()
    salt, h = hash_password(pw)
    cfg["salt"] = salt
    cfg["password_hash"] = h
    save_config(cfg)
    print("✓ Password changed.")


def cmd_uninstall(args) -> None:
    cfg = load_config()
    if cfg:
        _verify_auth(cfg)
    # Clear hosts
    try:
        clear_block()
    except PermissionError as e:
        print(f"✗ {e}")
        sys.exit(1)
    # Remove service
    uninstall_service()
    # Remove config (try all locations)
    from .config import _all_config_paths

    removed_any = False
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
                print(f"✓ Removed {p}")
                removed_any = True
        except PermissionError as e:
            # Try unlock via lock helper before giving up
            try:
                from .lock import unlock_file

                unlock_file(p)
                p.unlink()
                print(f"✓ Removed {p}")
                removed_any = True
                continue
            except Exception:
                pass
            print(f"✗ Permission denied removing {p}: {e}")
            sys.exit(1)
    if not removed_any:
        from .config import _config_path

        p = _config_path()
        if p.exists():
            try:
                from .lock import unlock_file

                unlock_file(p)
            except Exception:
                pass
            p.unlink()
    print("✓ Uninstalled. All blocks removed and autostart disabled.")


def cmd_update(args) -> None:
    """Self-update via git or install.sh – no sudo, no pip."""
    from .update import perform_update

    # --version shortcut handled in main(), but also support here
    if getattr(args, "version", False):
        print(__version__)
        return
    rc = perform_update(check_only=getattr(args, "check", False), force=getattr(args, "force", False))
    sys.exit(rc)


def cmd_version(args) -> None:
    print(__version__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="keep-focused",
        description="keep-focused – interactive CLI app to block distracting websites (Debian, all browsers). Run without arguments to launch the app.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Run without arguments to launch the interactive app:

  keep-focused
  keep-focused update          # self-update, no sudo/pip (like opencode)

Or use commands for scripting (requires password where noted):

  keep-focused setup --sites facebook.com x.com
  keep-focused status
  keep-focused block youtube.com reddit.com   # password
  keep-focused unblock spotify.com            # password
  keep-focused disable                        # password

Suggested sites: """ + ", ".join(SUGGESTED_SITES) + """
        """,
    )
    p.add_argument("--version", "-v", action="store_true", help="Show version")
    sub = p.add_subparsers(dest="command")

    # setup
    sp = sub.add_parser("setup", help="Interactive setup: choose sites, set password, enable autostart")
    sp.add_argument("--sites", nargs="*", help="Pre-select sites to block (bypasses prompt for them)")
    sp.add_argument("--password", help="Set password non-interactively (for scripting, min 20 chars)")
    sp.add_argument("--force", action="store_true", help="Re-run setup even if already configured")
    sp.set_defaults(func=cmd_setup)

    sub.add_parser("status", help="Show blocked sites and whether blocking is active").set_defaults(func=cmd_status)

    # internal apply
    ap = sub.add_parser("apply", help=argparse.SUPPRESS)
    ap.set_defaults(func=cmd_apply)

    # block / add
    bp = sub.add_parser("block", help="Block site(s) (requires password)")
    bp.add_argument("sites", nargs="*", help="Domains to block (e.g. facebook.com)")
    bp.set_defaults(func=cmd_block)
    addp = sub.add_parser("add", help="Alias for block")
    addp.add_argument("sites", nargs="*", help="Domains to block")
    addp.set_defaults(func=cmd_block)

    # unblock / remove
    ub = sub.add_parser("unblock", help="Unblock site(s) (requires password)")
    ub.add_argument("sites", nargs="*", help="Domains to unblock")
    ub.set_defaults(func=cmd_unblock)
    rp = sub.add_parser("remove", help="Alias for unblock")
    rp.add_argument("sites", nargs="*", help="Domains to unblock")
    rp.set_defaults(func=cmd_unblock)

    sub.add_parser("list", help="List blocked sites").set_defaults(func=cmd_list)
    sub.add_parser("ls", help="Alias for list").set_defaults(func=cmd_list)

    ep = sub.add_parser("enable", help="Enable blocking (requires password)")
    ep.set_defaults(func=cmd_enable)

    dp = sub.add_parser("disable", help="Disable blocking (requires password)")
    dp.set_defaults(func=cmd_disable)

    pp = sub.add_parser("passwd", help="Change password (requires old password)")
    pp.add_argument("--password", help="New password non-interactively (min 20 chars)")
    pp.set_defaults(func=cmd_passwd)

    up = sub.add_parser("uninstall", help="Remove all blocks, autostart and config (requires password)")
    up.set_defaults(func=cmd_uninstall)

    upd = sub.add_parser("update", help="Self-update to latest version (no sudo, no pip, like opencode)")
    upd.add_argument("--check", action="store_true", help="Check for updates without installing")
    upd.add_argument("--force", action="store_true", help="Force reinstall even if up to date")
    upd.set_defaults(func=cmd_update)

    sub.add_parser("version", help="Show version").set_defaults(func=cmd_version)

    return p


def main() -> None:
    # --version / --help early (before TUI)
    if len(sys.argv) == 2 and sys.argv[1] in ("--help", "-h"):
        parser = build_parser()
        parser.print_help()
        sys.exit(0)
    if len(sys.argv) == 2 and sys.argv[1] in ("--version", "-v"):
        print(__version__)
        sys.exit(0)
    # Support `keep-focused --version` via global flag as well
    if "--version" in sys.argv or "-v" in sys.argv:
        # Let argparse handle it (will set args.version)
        pass

    # No arguments → launch interactive TUI (like opencode / claude code)
    if len(sys.argv) == 1:
        from .tui import run_tui

        run_tui()
        return

    parser = build_parser()
    args = parser.parse_args()
    # Handle global --version flag
    if getattr(args, "version", False):
        print(__version__)
        sys.exit(0)
    if not hasattr(args, "func"):
        # Unknown args → launch TUI as well (handles `keep-focused` with stray args)
        from .tui import run_tui

        run_tui()
        return
    args.func(args)
