"""Textual app: actions menu, dialog arrow navigation, and how `keep-focused` launches it."""

import asyncio
import sys
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from textual.app import App

import keep_focused.app as app_mod
from keep_focused.app import ConfirmScreen, KeepFocusedApp, NewPasswordScreen, PasswordScreen

CFG = {"password_hash": "x", "salt": "x", "enabled": True, "blocked_sites": ["x.com"]}


class _Host(App):
    """Bare app that opens one dialog, so dialogs can be driven on their own."""

    def __init__(self, screen) -> None:
        super().__init__()
        self._dialog = screen

    def on_mount(self) -> None:
        self.push_screen(self._dialog)


def _drive(screen, steps):
    """Open `screen`, then for each (key, expected focused id) press the key and check focus."""

    async def run():
        async with _Host(screen).run_test() as pilot:
            await pilot.pause()
            for key, expected in steps:
                if key:
                    await pilot.press(key)
                    await pilot.pause()
                assert pilot.app.focused is not None and pilot.app.focused.id == expected, (key, expected, pilot.app.focused)

    asyncio.run(run())


@contextmanager
def _main_app_patches(update=False):
    """Run the main app on fake config/state, with a fake update check result."""
    with patch.object(app_mod, "load_config", lambda: dict(CFG)), \
         patch.object(app_mod, "is_block_active", lambda: True), \
         patch.object(app_mod, "is_service_enabled", lambda: True), \
         patch.object(app_mod, "update_available", lambda: update):
        yield


def _update_label(update):
    async def run():
        with _main_app_patches(update):
            app = KeepFocusedApp()
            async with app.run_test() as pilot:
                await app.workers.wait_for_complete()
                await pilot.pause()
                return str(app.main.query_one("#update-status").render())

    return asyncio.run(run())


def test_top_bar_shows_update_available():
    assert _update_label(True) == "Update available"


def test_top_bar_shows_up_to_date():
    assert _update_label(False) == "Up to date"


def test_top_bar_shows_nothing_when_offline():
    assert _update_label(None) == ""


def test_actions_menu_has_update_not_check_for_updates():
    labels = [label for _, _, label in app_mod.MainScreen.ACTIONS]
    assert "Update" in labels
    assert "Check for updates" not in labels


def test_actions_menu_enter_opens_change_password():
    async def run():
        with _main_app_patches():
            app = KeepFocusedApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                actions = app.main.query_one("#actions")
                ids = [actions.get_option_at_index(i).id for i in range(actions.option_count)]
                actions.highlighted = ids.index("password")
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, PasswordScreen)

    asyncio.run(run())


def test_password_dialog_arrows():
    _drive(PasswordScreen(CFG, "why"), [
        (None, "pw"),
        ("left", "pw"),      # ←→ inside a field move the text cursor, not focus
        ("up", "pw"),
        ("down", "ok"),      # ↓ from the field lands on the primary button
        ("down", "ok"),
        ("left", "cancel"),
        ("left", "cancel"),  # stops at the first button
        ("right", "ok"),
        ("right", "ok"),     # stops at the last button
        ("up", "pw"),
    ])


def test_new_password_dialog_arrows():
    _drive(NewPasswordScreen(), [
        (None, "pw1"),
        ("down", "pw2"),
        ("down", "ok"),
        ("left", "cancel"),
        ("up", "pw2"),       # ↑ from the buttons goes to the last field
        ("up", "pw1"),
        ("up", "pw1"),
    ])


def test_confirm_dialog_arrows():
    _drive(ConfirmScreen("Pause", "sure?", "Pause"), [
        (None, "yes"),
        ("left", "no"),
        ("right", "yes"),
        ("up", "yes"),       # no fields to go up to
        ("down", "yes"),
    ])


def test_main_launches_app_in_terminal():
    from keep_focused import cli

    with patch.object(sys, "argv", ["keep-focused"]), \
         patch.object(app_mod, "can_run_app", return_value=True), \
         patch.object(app_mod, "run_app") as run_app:
        cli.main()
    run_app.assert_called_once()


def test_main_without_terminal_exits():
    from keep_focused import cli

    with patch.object(sys, "argv", ["keep-focused"]), \
         patch.object(app_mod, "can_run_app", return_value=False), \
         patch.object(app_mod, "run_app") as run_app:
        with pytest.raises(SystemExit):
            cli.main()
    run_app.assert_not_called()


def test_only_selected_dialog_button_is_highlighted():
    class Styled(_Host):
        CSS = KeepFocusedApp.CSS

    async def run():
        async with Styled(PasswordScreen(CFG, "why")).run_test() as pilot:
            await pilot.pause()
            ok, cancel = pilot.app.screen.query_one("#ok"), pilot.app.screen.query_one("#cancel")
            assert ok.styles.background == cancel.styles.background  # typing: neither stands out
            await pilot.press("down")
            await pilot.pause()
            assert ok.styles.background != cancel.styles.background
            highlight = ok.styles.background
            await pilot.press("left")
            await pilot.pause()
            assert cancel.styles.background == highlight
            assert ok.styles.background != highlight

    asyncio.run(run())
