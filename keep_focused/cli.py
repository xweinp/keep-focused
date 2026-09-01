"""CLI for keep-focused – Click + Rich (no legacy fallback)."""

import sys

import rich_click as click
import rich_click.rich_click as rc

# ── Rich-Click styling ──────────────────────────────────────────────────────
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
    "[dim]Password (≥20 chars, PBKDF2) required for [cyan]block/unblock/enable/disable/uninstall[/].[/]\n"
    "[dim]All blocking is system-wide (Chrome, Firefox, etc.) via /etc/hosts.[/]"
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
        "[bold]Examples:[/]  [dim]keep-focused status[/]  •  "
        "[dim]keep-focused block youtube.com[/] [dim]# 🔒[/]  •  "
        "[dim]keep-focused unblock spotify.com[/] •  "
        "[dim]keep-focused update --check[/]\n"
        f"[bold]Suggested:[/] [dim]{', '.join(SUGGESTED_SITES)}[/]"
    )


@click.group(
    name="keep-focused",
    context_settings=dict(help_option_names=["-h", "--help"]),
    help=(
        "[bold cyan]keep-focused[/] — block distracting websites [dim]system-wide via /etc/hosts[/]\n\n"
        "Works in [bold]Chrome, Firefox, any browser[/]. "
        "All commands are listed below."
    ),
    epilog=_epilog(),
)
@click.version_option(__version__, "--version", "-v", prog_name="keep-focused", message="%(version)s")
def cli():
    pass


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


def _do_status():
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


@cli.command("status", help="Show [cyan]blocked sites[/], [dim]hosts[/] state & [dim]autostart[/] status")
def status_cmd():
    _do_status()


def _do_apply():
    """Internal: re-apply from config (used by systemd). No password needed."""
    cfg = load_config()
    if cfg is None:
        sys.exit(0)
    try:
        apply_block(cfg.get("blocked_sites", []), enabled=cfg.get("enabled", True))
    except PermissionError:
        click.echo("apply: permission denied (need root)", err=True)
        sys.exit(1)


@cli.command("apply", hidden=True)
def apply_cmd():
    """[dim]Internal: re-apply from config (used by systemd). No password needed.[/]"""
    _do_apply()


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


def _do_enable():
    cfg = _require_setup()
    _verify_auth(cfg)
    cfg["enabled"] = True
    save_config(cfg)
    if cfg["blocked_sites"]:
        apply_block(cfg["blocked_sites"], enabled=True)
        click.echo(f"✓ Blocking enabled ({len(cfg['blocked_sites'])} sites).")
    else:
        click.echo("No sites to block. Add some with: keep-focused block <site>")


@cli.command("enable", help="Enable blocking ([yellow]🔒 password[/]) — re-applies [dim]/etc/hosts[/]")
def enable():
    _do_enable()


def _do_disable():
    cfg = _require_setup()
    _verify_auth(cfg)
    cfg["enabled"] = False
    save_config(cfg)
    clear_block()
    click.echo("✓ Blocking disabled. All sites reachable. Enable again with: keep-focused enable")


@cli.command("disable", help="Disable blocking ([yellow]🔒 password[/]) — makes sites reachable")
def disable():
    _do_disable()


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


def _do_uninstall():
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


@cli.command("uninstall", help="[red]Remove all blocks[/], autostart and config ([yellow]🔒 password[/])")
def uninstall():
    _do_uninstall()


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


def _do_version():
    click.echo(__version__) if hasattr(click, "echo") else print(__version__)


@cli.command("version", help="Show [dim]version[/]")
def version():
    _do_version()


# ---------------------------------------------------------------------------
# Backwards compatibility: build_parser
# ---------------------------------------------------------------------------

def build_parser():
    """Deprecated: use `cli` (Click group) directly.

    Kept only to not break external imports; returns the Click group.
    No argparse is constructed anymore — the old shim is removed.
    """
    return cli


def main() -> None:
    cli(prog_name="keep-focused")
