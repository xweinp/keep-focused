"""Full-screen terminal app (Textual) – the UI for `keep-focused`."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from typing import Callable, TypeVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from . import DEFAULT_SELECTED, SUGGESTED_SITES, __version__
from .auth import MIN_PASSWORD_LENGTH, hash_password, verify_password
from .config import _all_config_paths, default_config, load_config, save_config
from .hosts import apply_block, clear_block, is_block_active, normalize_domain
from .systemd import install_service, is_service_enabled, uninstall_service
from .update import update_available


def can_run_app() -> bool:
    """True when the full-screen app can take over the terminal."""
    return sys.stdout.isatty() and sys.stdin.isatty()


def _sudo_needs_password() -> bool:
    if os.geteuid() == 0 or not shutil.which("sudo"):
        return False
    return subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0


def _remove_configs() -> None:
    from .lock import unlock_file

    for p in _all_config_paths():
        if not p.exists():
            continue
        try:
            unlock_file(p)
        except Exception:
            pass
        try:
            p.unlink()
        except PermissionError:
            subprocess.run(["sudo", "rm", "-f", str(p)], capture_output=True, check=False)
        try:
            p.parent.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


R = TypeVar("R")


class Dialog(ModalScreen[R]):
    """Modal with arrow navigation: ↑↓ between fields and the button row, ←→ between buttons.

    ↓ from the last field lands on the primary button (id "ok" or "yes").
    """

    BINDINGS = [
        Binding("down", "nav_down", show=False),
        Binding("up", "nav_up", show=False),
        Binding("left", "nav_side(-1)", show=False),
        Binding("right", "nav_side(1)", show=False),
    ]

    def _fields(self) -> list[Input]:
        return [w for w in self.query(Input) if w.display]

    def _buttons(self) -> list[Button]:
        return list(self.query(Button))

    def action_nav_down(self) -> None:
        fields = self._fields()
        if self.focused in fields:
            i = fields.index(self.focused)
            if i + 1 < len(fields):
                fields[i + 1].focus()
                return
            buttons = self._buttons()
            primary = [b for b in buttons if b.id in ("ok", "yes")]
            (primary or buttons)[-1].focus()

    def action_nav_up(self) -> None:
        fields = self._fields()
        if self.focused in fields:
            i = fields.index(self.focused)
            if i > 0:
                fields[i - 1].focus()
        elif isinstance(self.focused, Button) and fields:
            fields[-1].focus()

    def action_nav_side(self, step: int) -> None:
        buttons = self._buttons()
        if self.focused in buttons:
            i = buttons.index(self.focused) + step
            buttons[max(0, min(i, len(buttons) - 1))].focus()


class ConfirmScreen(Dialog[bool]):
    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel")]

    def __init__(self, title: str, message: str, confirm: str = "Confirm", danger: bool = False) -> None:
        super().__init__()
        self._title, self._message, self._confirm, self._danger = title, message, confirm, danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog" + (" -danger" if self._danger else "")) as d:
            d.border_title = self._title
            yield Static(self._message, classes="dialog-body")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="no")
                yield Button(self._confirm, id="yes")

    def on_mount(self) -> None:
        self.query_one("#yes", Button).focus()

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class PasswordScreen(Dialog[bool]):
    """Ask for the unlock password; dismisses True only once it verifies."""

    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel")]

    def __init__(self, cfg: dict, reason: str) -> None:
        super().__init__()
        self._cfg, self._reason = cfg, reason

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog") as d:
            d.border_title = "🔒 Password required"
            yield Static(self._reason, classes="dialog-body")
            yield Input(password=True, placeholder="Your keep-focused password", id="pw")
            yield Static("", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Unlock", id="ok")

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def _submit(self) -> None:
        field = self.query_one("#pw", Input)
        if verify_password(field.value, self._cfg["salt"], self._cfg["password_hash"]):
            self.dismiss(True)
            return
        field.value = ""
        self.query_one(".error", Static).update("✗ Wrong password — try again")
        field.focus()

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(False)


class NewPasswordScreen(Dialog["str | None"]):
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, title: str = "Set a password") -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog") as d:
            d.border_title = self._title
            yield Static(
                f"You'll need it to unblock sites or pause blocking.\n"
                f"Use at least [b]{MIN_PASSWORD_LENGTH} characters[/b] — a long phrase works best,\n"
                f"[dim]e.g. correct-horse-battery-staple-focus[/]",
                classes="dialog-body",
            )
            yield Input(password=True, placeholder="New password", id="pw1")
            yield Static("", id="meter")
            yield Input(password=True, placeholder="Repeat password", id="pw2")
            yield Static("", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save password", id="ok")

    def on_mount(self) -> None:
        self._update_meter("")

    def _update_meter(self, value: str) -> None:
        n = len(value)
        width = 24
        filled = min(width, round(width * n / MIN_PASSWORD_LENGTH))
        bar = "━" * filled + "╌" * (width - filled)
        colour = "$success" if n >= MIN_PASSWORD_LENGTH else "$warning"
        self.query_one("#meter", Static).update(f"[{colour}]{bar}[/]  [dim]{n}/{MIN_PASSWORD_LENGTH}[/]")

    @on(Input.Changed, "#pw1")
    def _changed(self, event: Input.Changed) -> None:
        self._update_meter(event.value)

    @on(Input.Submitted, "#pw1")
    def _next(self) -> None:
        self.query_one("#pw2", Input).focus()

    @on(Input.Submitted, "#pw2")
    @on(Button.Pressed, "#ok")
    def _submit(self) -> None:
        p1 = self.query_one("#pw1", Input).value
        p2 = self.query_one("#pw2", Input).value
        error = self.query_one(".error", Static)
        if len(p1) < MIN_PASSWORD_LENGTH:
            error.update(f"✗ Too short — {len(p1)} of {MIN_PASSWORD_LENGTH} characters")
            self.query_one("#pw1", Input).focus()
        elif p1 != p2:
            error.update("✗ Passwords don't match")
            self.query_one("#pw2", Input).value = ""
            self.query_one("#pw2", Input).focus()
        else:
            self.dismiss(p1)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Full screens – driven by arrows, Enter and Esc only
# ---------------------------------------------------------------------------

ADD_ROW, SAVE_ROW = "__add__", "__save__"


class HintBar(Static):
    """One-line key legend at the bottom of a screen."""


class SiteSelectScreen(Screen["list[str] | None"]):
    """Site list: Enter toggles a site, the Save row finishes, Esc goes back.

    mode: 'setup', 'block' or 'unblock'.
    """

    BINDINGS = [Binding("escape", "back", "Back")]

    TEXTS = {
        "setup": ("Pick sites to block", "Enter ticks or unticks a site · choose ✓ Save when done"),
        "block": ("Block more sites", "Unticking a site unblocks it (needs your password)"),
        "unblock": ("Unblock sites", "Untick the sites you want back · needs your password"),
    }

    def __init__(self, mode: str, current: set[str]) -> None:
        super().__init__()
        self._mode, self._current = mode, set(current)
        if mode == "unblock":
            self._domains = sorted(self._current)
        else:
            self._domains = SUGGESTED_SITES + sorted(self._current - set(SUGGESTED_SITES))
        self._selected = set(self._current)

    def compose(self) -> ComposeResult:
        title, sub = self.TEXTS[self._mode]
        yield Static(f"[b]{title}[/b]", classes="screen-title")
        yield Static(sub, classes="screen-sub")
        with Vertical(classes="panel", id="picker-panel") as panel:
            panel.border_title = "Sites"
            yield OptionList(*self._options(), id="picker")
        yield Input(placeholder="Type a website, e.g. news.ycombinator.com", id="custom")
        yield HintBar("")

    def _site_prompt(self, domain: str) -> Text:
        on = domain in self._selected
        text = Text.assemble(("  ✓  " if on else "  ·  ", "bold green" if on else "dim"), (domain, "" if on else "dim"))
        if self._mode == "block" and domain in self._current:
            text.append("   blocked now", style="dim")
        return text

    def _options(self) -> list:
        options: list = [Option(self._site_prompt(d), id=d) for d in self._domains]
        options.append(None)  # separator
        if self._mode != "unblock":
            options.append(Option(Text.assemble(("  +  ", "bold"), "Add another website…"), id=ADD_ROW))
        options.append(Option(Text.assemble(("  ✓  ", "bold green"), ("Save", "bold")), id=SAVE_ROW))
        return options

    def on_mount(self) -> None:
        self.query_one("#custom").display = False
        self.query_one("#picker").focus()
        self._update_hint()

    def _update_hint(self) -> None:
        typing = self.query_one("#custom").display
        self.query_one(HintBar).update(
            "[b]Enter[/b] add   [b]Esc[/b] back to list"
            if typing
            else f"[b]↑↓[/b] move   [b]Enter[/b] tick / choose   [b]Esc[/b] cancel"
            f"        [dim]{len(self._selected)} selected[/]"
        )

    @on(OptionList.OptionSelected, "#picker")
    def _chosen(self, event: OptionList.OptionSelected) -> None:
        picker = self.query_one("#picker", OptionList)
        option_id = event.option.id
        if option_id == SAVE_ROW:
            self.dismiss(sorted(self._selected))
        elif option_id == ADD_ROW:
            custom = self.query_one("#custom", Input)
            custom.display = True
            custom.focus()
        else:
            self._selected ^= {option_id}
            picker.replace_option_prompt(option_id, self._site_prompt(option_id))
        self._update_hint()

    @on(Input.Submitted, "#custom")
    def _add_custom(self, event: Input.Submitted) -> None:
        picker = self.query_one("#picker", OptionList)
        added = []
        for raw in event.value.split(","):
            d = normalize_domain(raw)
            if not d or "." not in d:
                continue
            self._selected.add(d)
            if d in self._domains:
                picker.replace_option_prompt(d, self._site_prompt(d))
            else:
                self._domains.append(d)
            added.append(d)
        if added:
            highlighted = picker.highlighted
            picker.clear_options()
            picker.add_options(self._options())
            picker.highlighted = highlighted
            self.notify(", ".join(added), title="Added")
        elif event.value.strip():
            self.notify(f"'{event.value.strip()}' isn't a website", severity="warning")
            return
        self._close_input()

    def _close_input(self) -> None:
        custom = self.query_one("#custom", Input)
        custom.value = ""
        custom.display = False
        self.query_one("#picker").focus()
        self._update_hint()

    def action_back(self) -> None:
        if self.query_one("#custom").display:
            self._close_input()
        else:
            self.dismiss(None)


class WelcomeScreen(Screen[bool]):
    BINDINGS = [Binding("escape", "dismiss(False)", "Quit"), Binding("enter", "dismiss(True)", "Get started")]

    def compose(self) -> ComposeResult:
        with Vertical(id="welcome"):
            yield Static("◉ keep-focused", id="welcome-logo")
            yield Static("Block distracting websites — everywhere, for real.", id="welcome-tag")
            yield Static(
                "[$accent]●[/]  Works in every browser — blocked through [b]/etc/hosts[/b]\n"
                f"[$accent]●[/]  Guarded by a password of {MIN_PASSWORD_LENGTH}+ characters\n"
                "[$accent]●[/]  Re-applied automatically when you log in\n\n"
                "[dim]Your sudo password is needed once, to edit /etc/hosts.[/]",
                id="welcome-points",
            )
            yield Button("Get started  →", id="start", variant="primary")
        yield HintBar("[b]Enter[/b] get started   [b]Esc[/b] quit")

    def on_mount(self) -> None:
        self.query_one("#start").focus()

    @on(Button.Pressed, "#start")
    def _start(self) -> None:
        self.dismiss(True)


class MainScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.quit", "Quit"),
        Binding("left", "focus_panel('sites')", show=False),
        Binding("right", "focus_panel('actions')", show=False),
    ]

    ACTIONS = [
        ("add", "+", "Block more sites"),
        ("unblock", "−", "Unblock sites"),
        ("toggle", "‖", "Pause / resume blocking"),
        ("reapply", "↺", "Re-apply blocks"),
        ("password", "*", "Change password"),
        ("update", "↓", "Update"),
        ("uninstall", "×", "Uninstall"),
        ("quit", "←", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("◉ [b]keep-focused[/b]  [dim]stay sharp[/]", id="brand")
            yield Static("", id="update-status")
            yield Static(f"v{__version__}", id="version")
        with Horizontal(id="cards"):
            yield Static(id="card-state", classes="card")
            yield Static(id="card-sites", classes="card")
            yield Static(id="card-boot", classes="card")
        with Horizontal(id="body"):
            with Vertical(id="sites-panel", classes="panel") as sites:
                sites.border_title = "Blocked sites"
                sites.border_subtitle = "Enter unblocks"
                yield OptionList(id="sites")
            with Vertical(id="actions-panel", classes="panel") as actions:
                actions.border_title = "Actions"
                yield OptionList(*(self._action(*a) for a in self.ACTIONS), id="actions")
        yield HintBar("[b]↑↓[/b] move   [b]←→[/b] switch panel   [b]Enter[/b] choose   [b]Esc[/b] quit")

    @staticmethod
    def _action(action_id: str, icon: str, label: str) -> Option:
        return Option(Text.assemble((f" {icon} ", "bold"), "  ", label), id=action_id)

    def on_mount(self) -> None:
        self.query_one("#actions").focus()

    def show_update_status(self, available: bool | None) -> None:
        """Label left of the version: None (GitHub unreachable) shows nothing."""
        label = {True: "[b $success]Update available[/]", False: "Up to date", None: ""}[available]
        self.query_one("#update-status", Static).update(label)

    def action_focus_panel(self, which: str) -> None:
        self.query_one(f"#{which}").focus()

    def refresh_status(self, cfg: dict) -> None:
        sites = sorted(cfg.get("blocked_sites", []))
        enabled = cfg.get("enabled", True)
        active = is_block_active()
        autostart = is_service_enabled()

        state = self.query_one("#card-state", Static)
        state.set_classes("card " + ("-on" if enabled and active else "-off"))
        if enabled and active:
            state.update("[b $success]● Blocking on[/]\n[dim]in every browser[/]")
        elif enabled:
            state.update("[b $warning]! Not applied[/]\n[dim]choose Re-apply blocks[/]")
        else:
            state.update("[b $error]○ Paused[/]\n[dim]choose Pause / resume[/]")

        self.query_one("#card-sites", Static).update(
            f"[b]{len(sites)}[/b] site{'s' if len(sites) != 1 else ''} blocked"
        )
        boot = self.query_one("#card-boot", Static)
        boot.set_classes("card " + ("-on" if autostart else "-off"))
        boot.update(
            "[b]⟳ Autostart on[/b]\n[dim]re-applied on every login[/]"
            if autostart
            else "[b]⟳ Autostart off[/b]\n[dim]blocks may lapse after reboot[/]"
        )

        site_list = self.query_one("#sites", OptionList)
        site_list.clear_options()
        if sites:
            site_list.add_options(
                Option(Text.assemble(("✕ " if enabled else "· ", "red" if enabled else "dim"), s), id=s)
                for s in sites
            )
            site_list.highlighted = 0
        else:
            site_list.add_option(Option(Text("Nothing blocked yet — choose Block more sites", style="dim"), disabled=True))

    @on(OptionList.OptionSelected, "#actions")
    async def _run_action(self, event: OptionList.OptionSelected) -> None:
        await self.run_action(f"app.{event.option.id}")

    @on(OptionList.OptionSelected, "#sites")
    def _unblock_site(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.app.unblock_one(event.option.id)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class KeepFocusedApp(App):
    TITLE = "keep-focused"
    ENABLE_COMMAND_PALETTE = True

    CSS = """
    Screen { background: $background; }

    #topbar { height: 1; padding: 0 2; background: $panel; }
    #brand { width: 1fr; color: $accent; }
    #update-status { width: auto; color: $text-muted; margin-right: 2; }
    #version { width: auto; color: $text-muted; }

    #cards { height: 4; margin: 1 1 0 1; }
    .card { width: 1fr; height: 4; margin: 0 1; padding: 0 2; border: round $foreground 25%; }
    .card.-on { border: round $success; }
    .card.-off { border: round $error 70%; }

    #body { margin: 0 1; }
    .panel {
        border: round $foreground 25%;
        border-title-color: $accent;
        border-title-style: bold;
        border-subtitle-color: $text-muted;
        padding: 0 1;
        margin: 1 1 0 1;
    }
    .panel:focus-within { border: round $accent; }
    #sites-panel { width: 3fr; }
    #actions-panel { width: 2fr; min-width: 30; }
    OptionList { border: none; background: transparent; padding: 0; }
    OptionList:focus { border: none; }
    HintBar { dock: bottom; height: 1; padding: 0 2; background: $panel; color: $text-muted; }

    .screen-title { margin: 1 3 0 3; color: $accent; }
    .screen-sub { margin: 0 3; color: $text-muted; }
    #picker-panel { height: 1fr; margin: 1 2 1 2; }
    #custom { margin: 0 2 1 2; }
    .buttons { height: auto; align-horizontal: right; margin: 1 2 0 2; }
    .buttons Button { margin-left: 2; }
    Button:focus { text-style: bold; }
    /* Dialog buttons look alike; only the selected one is coloured. */
    .buttons Button:focus { background: $primary; color: $text; }
    .dialog.-danger .buttons #yes:focus { background: $error; }

    ModalScreen { align: center middle; background: $background 60%; }
    .dialog {
        width: 64; height: auto; padding: 1 2;
        background: $surface;
        border: round $accent;
        border-title-color: $accent;
        border-title-style: bold;
    }
    .dialog.-danger { border: round $error; border-title-color: $error; }
    .dialog-body { margin-bottom: 1; }
    .dialog Input { margin-bottom: 0; }
    .dialog .buttons { margin: 1 0 0 0; }
    .error { color: $error; height: 1; margin-top: 1; }
    #meter { height: 1; margin: 0 1 1 1; }

    #welcome { width: 64; height: auto; margin: 2 0; padding: 2 4; border: round $accent; }
    WelcomeScreen { align: center middle; }
    #welcome-logo { text-style: bold; color: $accent; text-align: center; }
    #welcome-tag { text-align: center; color: $text-muted; margin-bottom: 2; }
    #welcome-points { margin-bottom: 2; }
    #start { width: 100%; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.cfg: dict | None = load_config()
        self.theme = "tokyo-night"

    async def on_mount(self) -> None:
        self.main = MainScreen()
        await self.push_screen(self.main)
        self.check_for_update()
        if self.cfg is None or "password_hash" not in self.cfg:
            self.run_setup()
        else:
            self.refresh_status()

    @work(thread=True, exclusive=True, group="update-check")
    def check_for_update(self) -> None:
        available = update_available()
        self.call_from_thread(self.main.show_update_status, available)

    def refresh_status(self) -> None:
        self.cfg = load_config()
        if self.cfg is not None:
            self.main.refresh_status(self.cfg)

    # -- helpers ------------------------------------------------------------

    async def system(self, fn: Callable[[], object], what: str) -> bool:
        """Run a function that edits system files, getting sudo first if needed.

        sudo is asked for outside the full-screen UI (the app is suspended), so
        the password prompt is a normal terminal prompt. Returns False on error.
        """
        if _sudo_needs_password():
            with self.suspend():
                print(f"\n  ◉ keep-focused — {what}")
                print("    sudo needs your password to edit /etc/hosts.\n")
                ok = subprocess.run(["sudo", "-v"]).returncode == 0
            if not ok:
                self.notify("sudo authentication failed — nothing changed", severity="error")
                return False
        try:
            await asyncio.to_thread(fn)
        except PermissionError as e:
            self.notify(str(e), title="Permission denied", severity="error", timeout=8)
            return False
        except Exception as e:
            self.notify(str(e), title="Failed", severity="error", timeout=8)
            return False
        return True

    async def ask_password(self, reason: str) -> bool:
        return await self.push_screen_wait(PasswordScreen(self.cfg, reason))

    def _apply(self, sites: list[str], enabled: bool) -> Callable[[], None]:
        if sites and enabled:
            return lambda: apply_block(sites, enabled=True)
        return clear_block

    async def _commit_sites(self, sites: list[str]) -> bool:
        self.cfg["blocked_sites"] = sites
        save_config(self.cfg)
        return await self.system(self._apply(sites, self.cfg.get("enabled", True)), "updating blocked sites")

    # -- flows --------------------------------------------------------------

    @work(exclusive=True)
    async def run_setup(self) -> None:
        while True:
            if not await self.push_screen_wait(WelcomeScreen()):
                self.exit()
                return
            chosen = await self.push_screen_wait(SiteSelectScreen("setup", set(DEFAULT_SELECTED)))
            if chosen is None:
                continue
            pw = await self.push_screen_wait(NewPasswordScreen("Set your unlock password"))
            if pw is not None:
                break
        salt, h = hash_password(pw)
        self.cfg = default_config(h, salt, chosen)
        save_config(self.cfg)
        if await self.system(self._apply(self.cfg["blocked_sites"], True), "applying blocks"):
            self.notify(f"Blocking {len(chosen)} site(s)", title="You're set up")
        if not await asyncio.to_thread(install_service):
            self.notify("Could not enable autostart — blocks may lapse after reboot", severity="warning")
        self.refresh_status()

    @work(exclusive=True)
    async def action_add(self) -> None:
        current = set(self.cfg.get("blocked_sites", []))
        chosen = await self.push_screen_wait(SiteSelectScreen("block", current))
        if chosen is None or set(chosen) == current:
            return
        removed = current - set(chosen)
        if removed and not await self.ask_password(f"Unblocking [b]{', '.join(sorted(removed))}[/b]."):
            return
        self.cfg["enabled"] = True
        if await self._commit_sites(chosen):
            added = set(chosen) - current
            self.notify(
                "\n".join(filter(None, [
                    f"Blocked {', '.join(sorted(added))}" if added else "",
                    f"Unblocked {', '.join(sorted(removed))}" if removed else "",
                ])),
                title="Saved",
            )
        self.refresh_status()

    @work(exclusive=True)
    async def action_unblock(self) -> None:
        current = sorted(self.cfg.get("blocked_sites", []))
        if not current:
            self.notify("Nothing is blocked", severity="warning")
            return
        chosen = await self.push_screen_wait(SiteSelectScreen("unblock", set(current)))
        if chosen is None or chosen == current:
            return
        removed = sorted(set(current) - set(chosen))
        if not await self.ask_password(f"Unblocking [b]{', '.join(removed)}[/b]."):
            return
        if await self._commit_sites(chosen):
            self.notify(", ".join(removed), title="Unblocked")
        self.refresh_status()

    @work(exclusive=True)
    async def unblock_one(self, site: str) -> None:
        if not await self.ask_password(f"Unblocking [b]{site}[/b]."):
            return
        remaining = [s for s in self.cfg.get("blocked_sites", []) if s != site]
        if await self._commit_sites(remaining):
            self.notify(site, title="Unblocked")
        self.refresh_status()

    @work(exclusive=True)
    async def action_toggle(self) -> None:
        sites = self.cfg.get("blocked_sites", [])
        if self.cfg.get("enabled", True):
            if not await self.push_screen_wait(
                ConfirmScreen("Pause blocking", "Every blocked site becomes reachable until you resume.", "Pause")
            ):
                return
            if not await self.ask_password("Pausing all blocking."):
                return
            self.cfg["enabled"] = False
            save_config(self.cfg)
            if await self.system(clear_block, "pausing blocking"):
                self.notify("All sites reachable — press e to resume", title="Paused")
        else:
            self.cfg["enabled"] = True
            save_config(self.cfg)
            if await self.system(self._apply(sites, True), "resuming blocking"):
                self.notify(f"{len(sites)} site(s) blocked again", title="Resumed")
        self.refresh_status()

    @work(exclusive=True)
    async def action_reapply(self) -> None:
        sites = self.cfg.get("blocked_sites", [])
        if await self.system(self._apply(sites, self.cfg.get("enabled", True)), "re-applying blocks"):
            self.notify("Blocks re-applied")
        self.refresh_status()

    @work(exclusive=True)
    async def action_password(self) -> None:
        if not await self.ask_password("Confirm your current password to change it."):
            return
        pw = await self.push_screen_wait(NewPasswordScreen("New password"))
        if pw is None:
            return
        self.cfg["salt"], self.cfg["password_hash"] = hash_password(pw)
        save_config(self.cfg)
        self.notify("Password changed")

    def action_update(self) -> None:
        from .update import installed_version, perform_update

        with self.suspend():
            print(f"\n  ◉ keep-focused — checking for updates (current v{__version__})\n")
            perform_update(check_only=False, force=False)
            try:
                input("\n  Press Enter to return… ")
            except (EOFError, KeyboardInterrupt):
                pass
        if installed_version() not in (None, __version__):
            # This process still runs the old code; start the new one.
            self.exit(RESTART)

    @work(exclusive=True)
    async def action_uninstall(self) -> None:
        if not await self.push_screen_wait(
            ConfirmScreen(
                "Uninstall",
                "Removes every block, the autostart service and your config.\n"
                "The app itself stays in ~/.local/share/keep-focused.",
                "Uninstall",
                danger=True,
            )
        ):
            return
        if not await self.ask_password("Uninstalling keep-focused."):
            return

        def _uninstall() -> None:
            clear_block()
            uninstall_service()
            _remove_configs()

        if await self.system(_uninstall, "uninstalling"):
            self.exit("keep-focused removed all blocks. Bye — stay focused!")


RESTART = "__restart__"


def run_app() -> None:
    result = KeepFocusedApp().run()
    if result == RESTART:
        os.execv(sys.executable, [sys.executable, "-m", "keep_focused"])
    print(result or "Bye — stay focused!")
