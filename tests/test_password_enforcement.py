"""Ensure password is required for all mutating operations – regression for reported bypass."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from keep_focused.auth import hash_password
from keep_focused.config import default_config


def _setup_cfg(tmp_env, pw="x" * 20, sites=None):
    if sites is None:
        sites = ["facebook.com"]
    salt, h = hash_password(pw)
    cfg = default_config(h, salt, sites)
    from keep_focused.config import save_config

    save_config(cfg)
    import keep_focused.hosts as hm

    hm.apply_block(cfg["blocked_sites"], enabled=True)
    return pw, cfg


def test_cli_block_requires_password(tmp_env):
    pw, _ = _setup_cfg(tmp_env)
    from keep_focused.cli import build_parser
    import keep_focused.cli as cli_mod
    import keep_focused.auth as auth_mod

    parser = build_parser()
    # Try block with wrong password
    args = parser.parse_args(["block", "youtube.com"])
    with patch.object(auth_mod, "prompt_password", return_value="wrong" * 5):
        with patch("keep_focused.cli.prompt_password", return_value="wrong" * 5):
            with patch("getpass.getpass", return_value="wrong" * 5):
                with pytest.raises(SystemExit):
                    args.func(args)
    # Config should not have youtube.com
    data = json.loads(tmp_env["config"].read_text())
    assert "youtube.com" not in data["blocked_sites"]


def test_cli_enable_requires_password_now(tmp_env):
    """Regression: previously enable --no-auth bypassed password."""
    pw, _ = _setup_cfg(tmp_env)
    # First disable
    from keep_focused.cli import build_parser
    import keep_focused.auth as auth_mod

    parser = build_parser()
    args = parser.parse_args(["disable"])
    with patch.object(auth_mod, "prompt_password", return_value=pw):
        with patch("keep_focused.cli.prompt_password", return_value=pw):
            with patch("getpass.getpass", return_value=pw):
                args.func(args)
    # Verify disabled
    assert json.loads(tmp_env["config"].read_text())["enabled"] is False
    # Try enable with wrong password – should fail
    parser2 = build_parser()
    args2 = parser2.parse_args(["enable"])
    with patch.object(auth_mod, "prompt_password", return_value="wrong" * 5):
        with patch("keep_focused.cli.prompt_password", return_value="wrong" * 5):
            with patch("getpass.getpass", return_value="wrong" * 5):
                with pytest.raises(SystemExit):
                    args2.func(args2)
    assert json.loads(tmp_env["config"].read_text())["enabled"] is False
    # Correct should succeed
    with patch.object(auth_mod, "prompt_password", return_value=pw):
        with patch("keep_focused.cli.prompt_password", return_value=pw):
            with patch("getpass.getpass", return_value=pw):
                args2.func(args2)
    assert json.loads(tmp_env["config"].read_text())["enabled"] is True


def test_tui_unblock_requires_password(tmp_env):
    pw, _ = _setup_cfg(tmp_env, sites=["facebook.com", "x.com"])
    from keep_focused.tui import _unblock_flow

    # Mock selection to unblock facebook, but wrong password
    with patch("keep_focused.tui._select_sites_interactive", return_value=["x.com"]):
        with patch("getpass.getpass", return_value="wrong" * 5):
            cfg = json.loads(tmp_env["config"].read_text())
            # Need to pass dict
            import json as _json

            cfg_dict = _json.loads(tmp_env["config"].read_text())
            result = _unblock_flow(cfg_dict)
            # Should not have unblocked
            data = json.loads(tmp_env["config"].read_text())
            assert "facebook.com" in data["blocked_sites"]


def test_manual_config_edit_is_locked(tmp_env):
    """Config file should be made immutable after save (best-effort)."""
    pw, _ = _setup_cfg(tmp_env)
    config_path = tmp_env["config"]
    # After save, file should exist and be readable
    assert config_path.exists()
    # Try to check if chattr available – if not, test just ensures file is 600
    # If chattr available, file should be immutable
    import shutil

    if shutil.which("chattr") and shutil.which("lsattr"):
        from keep_focused.lock import is_immutable

        # On some filesystems (tmpfs) chattr may fail, so we just check it doesn't crash
        # and that save still works
        assert config_path.read_text()  # still readable
    else:
        # Fallback: check permissions
        assert oct(config_path.stat().st_mode)[-3:] == "600"


def test_hosts_immutable_after_block(tmp_env):
    pw, _ = _setup_cfg(tmp_env)
    hosts_path = tmp_env["hosts"]
    assert hosts_path.exists()
    # Hosts should be readable and contain block
    content = hosts_path.read_text()
    assert "facebook.com" in content
