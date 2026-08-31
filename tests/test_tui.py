import json
from pathlib import Path
from unittest.mock import patch

import pytest

from keep_focused.auth import hash_password
from keep_focused.config import default_config


def _make_input(vals):
    it = iter(vals)

    def _inp(prompt=""):
        try:
            return next(it)
        except StopIteration:
            return ""

    return _inp


def _make_getpass(vals):
    it = iter(vals)

    def _gp(prompt=""):
        try:
            return next(it)
        except StopIteration:
            return ""

    return _gp


def test_tui_setup_via_legacy(tmp_env):
    # Uses legacy input path because KEEP_FOCUSED_NO_ARROW is set
    from keep_focused.tui import _setup_flow

    with patch("builtins.input", side_effect=_make_input(["", ""])):
        with patch("getpass.getpass", side_effect=_make_getpass(["x" * 20, "x" * 20])):
            result = _setup_flow()
            assert result is True
            assert tmp_env["config"].exists()
            assert "facebook.com" in tmp_env["hosts"].read_text()


def test_tui_block_more_requires_password(tmp_env):
    pw = "y" * 20
    salt, h = hash_password(pw)
    cfg = default_config(h, salt, ["facebook.com"])
    from keep_focused.config import save_config

    save_config(cfg)
    import keep_focused.hosts as hm

    hm.apply_block(cfg["blocked_sites"], enabled=True)

    from keep_focused.tui import _block_more

    # Try with wrong password – should not change
    # Select youtube (7) then done
    with patch("builtins.input", side_effect=_make_input(["7", "d", ""])):
        with patch("getpass.getpass", side_effect=_make_getpass(["wrong" * 5])):
            before = json.loads(tmp_env["config"].read_text())["blocked_sites"]
            _block_more(cfg)
            after = json.loads(tmp_env["config"].read_text())["blocked_sites"]
            assert before == after  # no change

    # Correct password should add
    with patch("builtins.input", side_effect=_make_input(["7", "d", ""])):
        with patch("getpass.getpass", side_effect=_make_getpass([pw])):
            _block_more(cfg)
            after = json.loads(tmp_env["config"].read_text())["blocked_sites"]
            assert "youtube.com" in after


def test_tui_toggle_enable_requires_password_both_ways(tmp_env):
    pw = "z" * 20
    salt, h = hash_password(pw)
    cfg = default_config(h, salt, ["facebook.com"])
    from keep_focused.config import save_config
    import keep_focused.hosts as hm

    save_config(cfg)
    hm.apply_block(cfg["blocked_sites"], enabled=True)

    from keep_focused.tui import _toggle_enable

    # Disable with wrong password – should stay enabled
    cfg = json.loads(tmp_env["config"].read_text())
    # Need to pass dict, not reloaded? _toggle_enable expects dict
    import json as _json

    cfg_dict = _json.loads(tmp_env["config"].read_text())
    # Mock _verify_or_exit will be called inside
    with patch("builtins.input", side_effect=_make_input(["y", ""])):
        with patch("getpass.getpass", side_effect=_make_getpass(["wrong" * 5])):
            result = _toggle_enable(cfg_dict)
            assert result["enabled"] is True

    # Disable with correct
    cfg_dict = _json.loads(tmp_env["config"].read_text())
    with patch("builtins.input", side_effect=_make_input(["y", ""])):
        with patch("getpass.getpass", side_effect=_make_getpass([pw])):
            result = _toggle_enable(cfg_dict)
            assert result["enabled"] is False

    # Enable with wrong password – should stay disabled (fixed bypass)
    cfg_dict = _json.loads(tmp_env["config"].read_text())
    with patch("builtins.input", side_effect=_make_input(["", ""])):
        with patch("getpass.getpass", side_effect=_make_getpass(["wrong" * 5])):
            result = _toggle_enable(cfg_dict)
            assert result["enabled"] is False  # still disabled

    # Enable with correct
    cfg_dict = _json.loads(tmp_env["config"].read_text())
    with patch("builtins.input", side_effect=_make_input(["", ""])):
        with patch("getpass.getpass", side_effect=_make_getpass([pw])):
            result = _toggle_enable(cfg_dict)
            assert result["enabled"] is True


def test_tui_arrow_main_menu(tmp_env_arrow):
    from keep_focused.tui import _arrow_main_menu
    from unittest.mock import patch

    # When cfg is None, items are Setup/Quit
    with patch("keep_focused.tui.read_key", side_effect=["down", "enter"]):
        result = _arrow_main_menu(None)
        assert result == "quit"
    with patch("keep_focused.tui.read_key", side_effect=["enter"]):
        result = _arrow_main_menu(None)
        assert result == "setup"


def test_tui_arrow_checkbox(tmp_env_arrow):
    from keep_focused.tui import _arrow_select_sites

    with patch("keep_focused.tui.read_key", side_effect=["a", "enter"]):
        result = _arrow_select_sites(set(), "Test")
        from keep_focused import SUGGESTED_SITES

        assert len(result) == len(SUGGESTED_SITES)

    with patch("keep_focused.tui.read_key", side_effect=["q"]):
        result = _arrow_select_sites(set(["facebook.com"]), "Test")
        assert result is None
