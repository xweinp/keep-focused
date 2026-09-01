"""CLI for keep-focused – now powered by Click + Rich."""

import sys

import rich_click as click
import rich_click.rich_click as rc

# ── Rich-Click styling ────────────────────────────────────────────────────────
rc.USE_RICH_MARKUP = True
rc.USE_MARKDOWN = False
rc.SHOW_ARGUMENTS = True
rc.GROUP_ARGUMENTS_OPTIONS = True
rc.STYLE_HELPTEXT_FIRST_LINE = "bold cyan"
rc.STYLE_OPTION_DEFAULT = "cyan"
rc.STYLE_SWITCH = "bold cyan"
rc.STYLE_USAGE = "bold"
rc.STYLE_USAGE_COMMAND = "bold cyan"
rc.HEADER_TEXT = "🎯 [bold cyan]keep-focused[/] — stay productive  •  [dim]blocks distracting sites system-wide via /etc/hosts[/]"
rc.FOOTER_TEXT = (
    "[dim]Run [bold]keep-focused[/] with no args to launch the interactive TUI (like opencode).[/]\n"
    "[dim]Password (≥20 chars, PBKDF2) required for [cyan]block/unblock/enable/disable/uninstall[/].[/]"
)
rc.COMMAND_GROUPS = {
    "keep-focused": [
        {"name": "🚀 Getting Started", "commands": ["setup", "status"]},
        {"name": "🚫 Blocking", "commands": ["block", "add", "unblock", "remove", "list", "ls"]},
        {"name": "⚙️  Control", "commands": ["enable", "disable"]},
        {"name": "🔧 System", "commands": ["passwd", "uninstall", "update", "version"]},
    ]
}
rc.OPTION_GROUPS = {
    "keep-focused": [{"name": "Options", "options": ["--version", "--help"]}],
    "keep-focused setup": [
        {"name": "Setup Options", "options": ["--sites", "--password", "--force"]},
    ],
    "keep-focused block": [{"name": "Arguments", "options": ["sites"]}],
    "keep-focused passwd": [{"name": "Options", "options": ["--password"]}],
    "keep-focused update": [{"name": "Options", "options": ["--check", "--force"]}],
}
rc.STYLE_COMMANDS_TABLE_COLUMN_TYPES = {"command": "cyan", "help": "dim"}

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
        click.echo("✗ Not set up yet. Run: keep-focused")
        sys.exit(1)
    return cfg


def _verify_auth(cfg: dict) -> None:
    """Prompt for password and verify; exit on failure."""
    pw = prompt_password("Enter password to authorize: ")
    if not verify_password(pw, cfg["salt"], cfg["password_hash"]):
        click.echo("✗ Wrong password.")
        sys.exit(1)


def _print_suggested(selected: set[str] | None = None) -> None:
    click.echo("\nSuggested sites to block:")
    for i, site in enumerate(SUGGESTED_SITES, 1):
        mark = "●" if selected and site in selected else "○"
        default_mark = " [default]" if site in DEFAULT_SELECTED else ""
        click.echo(f"  {i:2}. {mark} {site}{default_mark}")


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------

def _epilog() -> str:
    return (
        "[bold]Examples:[/]  [dim]keep-focused[/] [dim]# TUI[/]  •  "
        "[dim]keep-focused update[/] [dim]# update[/]  •  "
        "[dim]keep-focused status[/] •  [dim]block/unblock with 🔒[/]\n"
        f"[bold]Suggested:[/] [dim]{', '.join(SUGGESTED_SITES)}[/]\n"
        "[dim]Tip: ↑/↓ + Space to toggle sites in the TUI.[/]"
    )


@click.group(
    name="keep-focused",
    context_settings=dict(help_option_names=["-h", "--help"]),
    invoke_without_command=True,
    help=(
        "[bold cyan]keep-focused[/] — block distracting websites [dim]system-wide via /etc/hosts[/]\n\n"
        "Works in [bold]Chrome, Firefox, any browser[/]. "
        "Run with [bold]no arguments[/] to launch the [cyan]interactive TUI[/] "
        "(like [italic]opencode[/] / [italic]claude code[/])."
    ),
    epilog=_epilog(),
)
@click.version_option(__version__, "--version", "-v", prog_name="keep-focused", message="%(version)s")
@click.pass_context
def cli(ctx):
    """Root group – launch TUI when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        # Click already handled --help / --version (exits before here).
        # For programmatic `CliRunner.invoke(cli, [])` we show help; real CLI with no args
        # is handled by `main()` which launches TUI before reaching Click.
        click.echo(ctx.get_help())
        ctx.exit(0)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _do_setup(sites_combined: list[str], password: str | None, force: bool) -> None:
    click.echo(BANNER)
    existing = load_config()
    if existing and not force:
        click.echo("Already set up. Use --force to re-run setup.")
        click.echo("Current blocked sites: " + (", ".join(existing.get("blocked_sites", [])) or "(none)"))
        return

    # Interactive site selection
    click.echo("Select sites to block during setup.")
    click.echo("We suggest these popular distractors (defaults pre-selected):")
    _print_suggested(set(DEFAULT_SELECTED))

    click.echo("\nEnter numbers comma-separated (e.g. 1,2,4,6)")
    click.echo("  - Press ENTER to accept defaults: facebook.com, x.com, linkedin.com, spotify.com")
    click.echo("  - Type 'a' for all suggested sites")
    click.echo("  - Type 'n' for none (you can add later)")
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
                    click.echo(f"  ! Ignoring out-of-range: {part}")
            except ValueError:
                chosen.append(part)
        seen: set[str] = set()
        uniq: list[str] = []
        for c in chosen:
            nc = normalize_domain(c)
            if nc not in seen:
                seen.add(nc)
                uniq.append(nc)
        chosen = uniq

    # Allow adding custom sites from --sites / extra positional
    if sites_combined:
        for s in sites_combined:
            nc = normalize_domain(s)
            if nc not in chosen:
                chosen.append(nc)

    if not chosen:
        click.echo("\nNo sites selected. You can add sites later with: sudo keep-focused add <site>")
    else:
        click.echo(f"\nWill block: {', '.join(chosen)}")

    # Password
    if password:
        pw = password
        if len(pw) < MIN_PASSWORD_LENGTH:
            click.echo(f"✗ Password too short ({len(pw)} chars). Must be at least {MIN_PASSWORD_LENGTH}.")
            sys.exit(1)
    else:
        click.echo(f"\nSet a password to protect unblocking (minimum {MIN_PASSWORD_LENGTH} characters).")
        click.echo("You will need this password to unblock or disable protection.")
        pw = prompt_new_password()

    salt, h = hash_password(pw)
    cfg = default_config(h, salt, chosen)
    try:
        save_config(cfg)
    except PermissionError as e:
        click.echo(f"✗ Permission denied writing config: {e}")
        click.echo("  Try: keep-focused (will prompt for sudo if needed)")
        sys.exit(1)

    try:
        apply_block(cfg["blocked_sites"], enabled=cfg["enabled"])
    except PermissionError as e:
        click.echo(f"✗ {e}")
        click.echo("  Hint: your sudo password may be required. Try running: keep-focused")
        sys.exit(1)

    click.echo(f"\n✓ Blocked {len(cfg['blocked_sites'])} site(s) (with www. variants → {len(cfg['blocked_sites'])*2} hosts entries).")
    click.echo("  System-wide: Chrome, Firefox, etc. will now show connection errors for blocked sites.")

    click.echo("\nEnabling autostart on boot (systemd)...")
    if install_service():
        click.echo("✓ Autostart enabled (keep-focused.service). Blocks re-applied on every boot.")
    else:
        click.echo("  ! systemd not available or not root. Blocks are active now,")
        click.echo("    but may need re-apply after reboot if hosts is reset.")
        click.echo("    Ensure keep-focused is run at boot via your init system.")

    click.echo("\nDone. Use 'keep-focused status' to verify.")
    click.echo("To unblock, you will need your password.")


@cli.command(
    "setup",
    help="[bold]Interactive setup[/] — choose sites, set password, enable autostart ([dim]first run[/])",
    context_settings=dict(allow_extra_args=True, ignore_unknown_options=True),
)
@click.option("--sites", "sites_opt", multiple=True, help="Pre-select sites to block ([cyan]repeatable[/], e.g. [dim]--sites facebook.com --sites x.com[/])")
@click.option("--password", help="Set password non-interactively for scripting ([yellow]min 20 chars[/])")
@click.option("--force", is_flag=True, help="Re-run setup even if already configured ([red]overwrites[/])")
@click.pass_context
def setup_cmd(ctx, sites_opt, password, force):
    # Merge --sites and stray positional args (supports `setup --sites a b` via ctx.args)
    extra_sites = tuple(ctx.args)
    sites_combined = list(sites_opt) + list(extra_sites)

    _do_setup(sites_combined, password, force)


@cli.command("status", help="Show [cyan]blocked sites[/], [dim]hosts[/] state & [dim]autostart[/] status")
def status_cmd():
    cfg = load_config()
    if cfg is None:
        click.echo("Not set up. Run: keep-focused")
        return
    click.echo(BANNER)
    click.echo(f"Enabled:        {'yes' if cfg.get('enabled') else 'no'}")
    click.echo(f"Blocked sites:  {len(cfg.get('blocked_sites', []))}")
    for s in sorted(cfg.get("blocked_sites", [])):
        click.echo(f"  - {s}  (also www.{s})")
    active = is_block_active()
    click.echo(f"Hosts active:   {'yes' if active else 'no'}")
    click.echo(f"Autostart:      {'enabled' if is_service_enabled() else 'disabled'}")
    hosts_domains = get_blocked_from_hosts()
    if hosts_domains:
        click.echo(f"Hosts entries:  {len(hosts_domains)} domains")
    click.echo(f"Password:       set (min {MIN_PASSWORD_LENGTH} chars, PBKDF2)")
    if not cfg.get("enabled") or not active:
        click.echo("\n⚠ Blocking is currently DISABLED – sites are reachable.")
    else:
        click.echo("\n✓ Blocking is ACTIVE – listed sites are unreachable in all browsers.")


@cli.command("apply", hidden=True)
def apply_cmd():
    """[dim]Internal: re-apply from config (used by systemd). No password needed.[/]"""
    cfg = load_config()
    if cfg is None:
        sys.exit(0)
    try:
        apply_block(cfg.get("blocked_sites", []), enabled=cfg.get("enabled", True))
    except PermissionError:
        click.echo("apply: permission denied (need root)", err=True)
        sys.exit(1)


def _block_impl(sites):
    cfg = _require_setup()
    _verify_auth(cfg)
    if not sites:
        click.echo("Usage: keep-focused block <site> [site ...]")
        sys.exit(1)
    added: list[str] = []
    for raw in sites:
        d = normalize_domain(raw)
        if not d or "." not in d:
            click.echo(f"  ! Skipping invalid domain: {raw}")
            continue
        if d not in cfg["blocked_sites"]:
            cfg["blocked_sites"].append(d)
            added.append(d)
        else:
            click.echo(f"  - Already blocked: {d}")
    if added:
        cfg["blocked_sites"] = sorted(set(cfg["blocked_sites"]))
        cfg["enabled"] = True
        save_config(cfg)
        apply_block(cfg["blocked_sites"], enabled=True)
        click.echo(f"✓ Blocked: {', '.join(added)} (plus www. variants)")
    else:
        click.echo("No new sites added.")


@cli.command("block", help="Block [cyan]site(s)[/] ([yellow]🔒 password[/]) — any website, not just suggested\n\n[dim]Examples:[/] [cyan]keep-focused block youtube.com reddit.com[/] [dim]or[/] [cyan]myfavouritegame.com[/]")
@click.argument("sites", nargs=-1, metavar="SITES")
def block(sites):
    _block_impl(sites)


@cli.command("add", help="[dim]Alias for[/] [cyan]block[/] — any website")
@click.argument("sites", nargs=-1, metavar="SITES")
def add(sites):
    _block_impl(sites)


def _unblock_impl(sites):
    cfg = _require_setup()
    _verify_auth(cfg)
    if not sites:
        click.echo("Usage: keep-focused unblock <site> [site ...]")
        sys.exit(1)
    removed: list[str] = []
    for raw in sites:
        d = normalize_domain(raw)
        if d.startswith("www."):
            d = d[4:]
        if d in cfg["blocked_sites"]:
            cfg["blocked_sites"].remove(d)
            removed.append(d)
        else:
            click.echo(f"  - Not blocked: {d}")
    if removed:
        save_config(cfg)
        if cfg["blocked_sites"] and cfg.get("enabled"):
            apply_block(cfg["blocked_sites"], enabled=True)
        elif not cfg["blocked_sites"]:
            clear_block()
        click.echo(f"✓ Unblocked: {', '.join(removed)}")
        if not cfg["blocked_sites"]:
            click.echo("  No sites left blocked.")
    else:
        click.echo("No sites removed.")


@cli.command("unblock", help="Unblock [cyan]site(s)[/] ([yellow]🔒 password[/])")
@click.argument("sites", nargs=-1, metavar="SITES")
def unblock(sites):
    _unblock_impl(sites)


@cli.command("remove", help="[dim]Alias for[/] [cyan]unblock[/]")
@click.argument("sites", nargs=-1, metavar="SITES")
def remove(sites):
    _unblock_impl(sites)


def _list_impl():
    cfg = _require_setup()
    sites = cfg.get("blocked_sites", [])
    if not sites:
        click.echo("(no sites blocked)")
        return
    for s in sorted(sites):
        click.echo(s)


@cli.command("list", help="List [cyan]blocked sites[/] (one per line)")
def list_cmd():
    _list_impl()


@cli.command("ls", help="[dim]Alias for[/] [cyan]list[/]")
def ls_cmd():
    _list_impl()


@cli.command("enable", help="Enable blocking ([yellow]🔒 password[/]) — re-applies [dim]/etc/hosts[/]")
def enable():
    cfg = _require_setup()
    _verify_auth(cfg)
    cfg["enabled"] = True
    save_config(cfg)
    if cfg["blocked_sites"]:
        apply_block(cfg["blocked_sites"], enabled=True)
        click.echo(f"✓ Blocking enabled ({len(cfg['blocked_sites'])} sites).")
    else:
        click.echo("No sites to block. Add some with: keep-focused block <site>")


@cli.command("disable", help="Disable blocking ([yellow]🔒 password[/]) — makes sites reachable")
def disable():
    cfg = _require_setup()
    _verify_auth(cfg)
    cfg["enabled"] = False
    save_config(cfg)
    clear_block()
    click.echo("✓ Blocking disabled. All sites reachable. Enable again with: keep-focused enable")


def _do_passwd(new_password: str | None) -> None:
    cfg = _require_setup()
    _verify_auth(cfg)
    click.echo(f"\nSet a new password (min {MIN_PASSWORD_LENGTH} chars).")
    if new_password:
        pw = new_password
        if len(pw) < MIN_PASSWORD_LENGTH:
            click.echo(f"✗ Too short ({len(pw)}). Need {MIN_PASSWORD_LENGTH}.")
            sys.exit(1)
    else:
        pw = prompt_new_password()
    salt, h = hash_password(pw)
    cfg["salt"] = salt
    cfg["password_hash"] = h
    save_config(cfg)
    click.echo("✓ Password changed.")


@cli.command("passwd", help="Change password ([yellow]🔒 old password[/] required, [dim]min 20 chars[/])")
@click.option("--password", "new_password", help="New password non-interactively ([yellow]min 20 chars[/])")
def passwd(new_password):
    _do_passwd(new_password)


@cli.command("uninstall", help="[red]Remove all blocks[/], autostart and config ([yellow]🔒 password[/])")
def uninstall():
    cfg = load_config()
    if cfg:
        _verify_auth(cfg)
    try:
        clear_block()
    except PermissionError as e:
        click.echo(f"✗ {e}")
        sys.exit(1)
    uninstall_service()
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
                click.echo(f"✓ Removed {p}")
                removed_any = True
        except PermissionError as e:
            try:
                from .lock import unlock_file

                unlock_file(p)
                p.unlink()
                click.echo(f"✓ Removed {p}")
                removed_any = True
                continue
            except Exception:
                pass
            click.echo(f"✗ Permission denied removing {p}: {e}")
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
    click.echo("✓ Uninstalled. All blocks removed and autostart disabled.")


def _do_update(check: bool, force: bool) -> None:
    from .update import perform_update

    rc = perform_update(check_only=check, force=force)
    sys.exit(rc)


@cli.command("update", help="Self-update to [cyan]latest version[/] ([dim]no sudo, no pip, like opencode[/])")
@click.option("--check", is_flag=True, help="Check for updates [dim]without installing[/]")
@click.option("--force", is_flag=True, help="Force reinstall even if up to date")
def update(check, force):
    """[dim]Self-update via git or install.sh – no sudo, no pip.[/]"""
    _do_update(check, force)


@cli.command("version", help="Show [dim]version[/]")
def version():
    click.echo(__version__)


# ---------------------------------------------------------------------------
# Backwards compatibility: build_parser
# ---------------------------------------------------------------------------

def build_parser():
    """Return the Click group.

    Previously returned an argparse.ArgumentParser. Kept for backwards compatibility;
    new code should use `cli` directly. For tests that still call `build_parser().parse_args`,
    we provide a minimal shim that raises a helpful error directing to CliRunner.
    """
    # Provide a shim object that mimics the old argparse parser for limited use.
    # The shim's parse_args will emulate old behavior by invoking Click via CliRunner
    # and returning a simple namespace with `func` attribute.
    # However, for full compatibility, we also expose the Click group itself as `build_parser()`
    # returns `cli`. Tests that expect argparse will need to be updated to use CliRunner.
    # To support both, we attach a `parse_args` attribute to the group.
    import argparse  # kept for compatibility

    # Build a minimal argparse parser for legacy tests if they rely on argparse API.
    # This mirrors the old implementation but is not used by `main()` anymore.
    # We keep it to avoid breaking external callers.
    p = argparse.ArgumentParser(
        prog="keep-focused",
        description="keep-focused – interactive CLI app to block distracting websites (Debian, all browsers). Run without arguments to launch the app.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nRun without arguments to launch the interactive app:\n\n"
        "  keep-focused\n"
        "  keep-focused update          # self-update, no sudo/pip (like opencode)\n\n"
        "Or use commands for scripting (requires password where noted):\n\n"
        "  keep-focused setup --sites facebook.com x.com\n"
        "  keep-focused status\n"
        "  keep-focused block youtube.com reddit.com   # password\n"
        "  keep-focused unblock spotify.com            # password\n"
        "  keep-focused disable                        # password\n\n"
        f"Suggested sites: {', '.join(SUGGESTED_SITES)}\n",
    )
    p.add_argument("--version", "-v", action="store_true", help="Show version")
    # Provide a dummy subparsers setup so that `parse_args` doesn't crash for legacy callers,
    # but the actual CLI is Click-based. We return the Click group as primary and also attach
    # a helper to allow `parser.parse_args` style tests to still run via Click.
    # To make legacy tests work, we implement a wrapper:
    class _Shim:
        def __init__(self, click_group, argparse_parser):
            self._click_group = click_group
            self._argparse_parser = argparse_parser

        def parse_args(self, args=None):
            # First try argparse parsing for legacy tests that expect `args.func`
            # If that succeeds and has func, return it
            try:
                ns = self._argparse_parser.parse_args(args)
                # If argparse succeeded and has func, return it (legacy path)
                if hasattr(ns, "func"):
                    return ns
            except SystemExit:
                # argparse would exit on unknown; fall through to Click handling
                raise
            # Fallback: use Click to parse and emulate Namespace
            # For new tests, they should use CliRunner directly, not this shim
            return self._argparse_parser.parse_args(args)

        def print_help(self):
            return self._argparse_parser.print_help()

        def __getattr__(self, name):
            return getattr(self._argparse_parser, name)

    # We still need to populate the argparse parser with subcommands for shim to work.
    # Re-create full argparse setup for shim (duplicate of old logic) – minimal for tests
    sub = p.add_subparsers(dest="command")

    def _dummy(*a, **kw):
        pass

    # setup
    sp = sub.add_parser("setup", help="Interactive setup: choose sites, set password, enable autostart")
    sp.add_argument("--sites", nargs="*", help="Pre-select sites to block (bypasses prompt for them)")
    sp.add_argument("--password", help="Set password non-interactively (for scripting, min 20 chars)")
    sp.add_argument("--force", action="store_true", help="Re-run setup even if already configured")

    def _setup_shim(args):
        sites = args.sites or []
        _do_setup(sites, args.password, args.force)

    sp.set_defaults(func=_setup_shim)

    sub.add_parser("status", help="Show blocked sites and whether blocking is active").set_defaults(func=lambda args: cli.commands["status"].callback())
    ap = sub.add_parser("apply", help=argparse.SUPPRESS)
    ap.set_defaults(func=lambda args: cli.commands["apply"].callback())
    bp = sub.add_parser("block", help="Block site(s) (requires password) — any website, not just suggested")
    bp.add_argument("sites", nargs="*", help="Domains to block (e.g. facebook.com or any custom myfavouritegame.com)")
    bp.set_defaults(func=lambda args: _block_impl(args.sites))
    addp = sub.add_parser("add", help="Alias for block — any website")
    addp.add_argument("sites", nargs="*", help="Domains to block (any website)")
    addp.set_defaults(func=lambda args: _block_impl(args.sites))
    ub = sub.add_parser("unblock", help="Unblock site(s) (requires password)")
    ub.add_argument("sites", nargs="*", help="Domains to unblock")
    ub.set_defaults(func=lambda args: _unblock_impl(args.sites))
    rp = sub.add_parser("remove", help="Alias for unblock")
    rp.add_argument("sites", nargs="*", help="Domains to unblock")
    rp.set_defaults(func=lambda args: _unblock_impl(args.sites))
    sub.add_parser("list", help="List blocked sites").set_defaults(func=lambda args: _list_impl())
    sub.add_parser("ls", help="Alias for list").set_defaults(func=lambda args: _list_impl())
    ep = sub.add_parser("enable", help="Enable blocking (requires password)")
    ep.set_defaults(func=lambda args: cli.commands["enable"].callback())
    dp = sub.add_parser("disable", help="Disable blocking (requires password)")
    dp.set_defaults(func=lambda args: cli.commands["disable"].callback())
    pp = sub.add_parser("passwd", help="Change password (requires old password)")
    pp.add_argument("--password", help="New password non-interactively (min 20 chars)")

    def _passwd_shim(args):
        _do_passwd(args.password)

    pp.set_defaults(func=_passwd_shim)
    up = sub.add_parser("uninstall", help="Remove all blocks, autostart and config (requires password)")
    up.set_defaults(func=lambda args: cli.commands["uninstall"].callback())
    upd = sub.add_parser("update", help="Self-update to latest version (no sudo, no pip, like opencode)")
    upd.add_argument("--check", action="store_true", help="Check for updates without installing")
    upd.add_argument("--force", action="store_true", help="Force reinstall even if up to date")

    def _update_shim(args):
        _do_update(args.check, args.force)

    upd.set_defaults(func=_update_shim)
    sub.add_parser("version", help="Show version").set_defaults(func=lambda args: click.echo(__version__))

    return _Shim(cli, p)


def main() -> None:
    # No arguments → launch interactive TUI (like opencode / claude code)
    if len(sys.argv) == 1:
        from .tui import run_tui

        run_tui()
        return

    # Delegate to Click group; it will handle all subcommands and exit codes.
    # Use prog_name="keep-focused" so help shows correct name.
    try:
        cli(prog_name="keep-focused")
    except SystemExit as e:
        # Re-raise to preserve exit code for callers / tests
        raise
