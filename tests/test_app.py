"""Textual app: actions menu, dialog arrow navigation, and how `keep-focused` launches it."""

import asyncio
import sys
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


def test_actions_menu_enter_opens_change_password():
    async def run():
        with patch.object(app_mod, "load_config", lambda: dict(CFG)), \
             patch.object(app_mod, "is_block_active", lambda: True), \
             patch.object(app_mod, "is_service_enabled", lambda: True):
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
