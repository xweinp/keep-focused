import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from keep_focused.auth import hash_password
from keep_focused.config import default_config


def _run_cli(monkeypatch, tmp_env, argv, mock_pw=None):
    # Helper to run CLI with mocked password
    from keep_focused.cli import build_parser
    import keep_focused.auth as auth_mod
    import keep_focused.cli as cli_mod

    parser = build_parser()
    args = parser.parse_args(argv)
    patches = []
    if mock_pw is not None:
        p1 = patch.object(auth_mod, "prompt_password", return_value=mock_pw)
        p2 = patch("keep_focused.cli.prompt_password", return_value=mock_pw)
        p3 = patch("getpass.getpass", return_value=mock_pw)
        patches = [p1, p2, p3]
        for p in patches:
            p.start()
    try:
        args.func(args)
    except SystemExit as e:
        if e.code not in (0, None):
            raise
    finally:
        for p in patches:
            p.stop()


def test_setup_and_status(tmp_env):
    hosts = tmp_env["hosts"]
    config = tmp_env["config"]
    pw = "x" * 20
    # Mock site selection input -> defaults
    with patch("builtins.input", return_value=""):
        _run_cli(None, tmp_env, ["setup", "--password", pw])
    assert config.exists()
    data = json.loads(config.read_text())
    assert "facebook.com" in data["blocked_sites"]
    assert hosts.read_text().count("facebook.com") > 0

    # Status should not require password
    from keep_focused.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["status"])
    # Should not raise
    args.func(args)


def test_block_and_unblock_requires_password(tmp_env):
    pw = "y" * 20
    with patch("builtins.input", return_value=""):
        _run_cli(None, tmp_env, ["setup", "--password", pw])

    # Block with correct password
    _run_cli(None, tmp_env, ["block", "youtube.com"], mock_pw=pw)
    data = json.loads(tmp_env["config"].read_text())
    assert "youtube.com" in data["blocked_sites"]

    # Block with wrong password should fail
    with pytest.raises(SystemExit):
        _run_cli(None, tmp_env, ["block", "reddit.com"], mock_pw="wrong" * 5)

    # Unblock with correct password
    _run_cli(None, tmp_env, ["unblock", "youtube.com"], mock_pw=pw)
    data = json.loads(tmp_env["config"].read_text())
    assert "youtube.com" not in data["blocked_sites"]

    # Unblock with www prefix should also work
    _run_cli(None, tmp_env, ["block", "tiktok.com"], mock_pw=pw)
    _run_cli(None, tmp_env, ["unblock", "www.tiktok.com"], mock_pw=pw)
    data = json.loads(tmp_env["config"].read_text())
    assert "tiktok.com" not in data["blocked_sites"]


def test_enable_disable_require_password(tmp_env):
    pw = "z" * 20
    with patch("builtins.input", return_value=""):
        _run_cli(None, tmp_env, ["setup", "--password", pw])

    # Disable requires password
    with pytest.raises(SystemExit):
        _run_cli(None, tmp_env, ["disable"], mock_pw="wrong" * 5)
    _run_cli(None, tmp_env, ["disable"], mock_pw=pw)
    data = json.loads(tmp_env["config"].read_text())
    assert data["enabled"] is False

    # Enable also requires password now (fixed bypass)
    with pytest.raises(SystemExit):
        _run_cli(None, tmp_env, ["enable"], mock_pw="wrong" * 5)
    _run_cli(None, tmp_env, ["enable"], mock_pw=pw)
    data = json.loads(tmp_env["config"].read_text())
    assert data["enabled"] is True


def test_update_check(tmp_env, monkeypatch):
    # Mock remote version fetch to avoid network
    import keep_focused.update as upd

    monkeypatch.setattr(upd, "_fetch_remote_version", lambda: "0.1.0")
    from keep_focused.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["update", "--check"])
    # Should not raise, should exit 0
    try:
        args.func(args)
    except SystemExit as e:
        assert e.code == 0


def test_passwd_change(tmp_env):
    pw = "a" * 20
    new_pw = "b" * 20
    with patch("builtins.input", return_value=""):
        _run_cli(None, tmp_env, ["setup", "--password", pw])
    # Change password requires old password
    with patch("keep_focused.cli.prompt_new_password", return_value=new_pw):
        with patch("keep_focused.auth.prompt_password", return_value=pw):
            with patch("keep_focused.cli.prompt_password", return_value=pw):
                _run_cli(None, tmp_env, ["passwd"])
    data = json.loads(tmp_env["config"].read_text())
    from keep_focused.auth import verify_password

    assert verify_password(new_pw, data["salt"], data["password_hash"])


def test_uninstall_requires_password(tmp_env):
    pw = "c" * 20
    with patch("builtins.input", return_value=""):
        _run_cli(None, tmp_env, ["setup", "--password", pw])
    assert tmp_env["config"].exists()
    # Wrong password should fail
    with pytest.raises(SystemExit):
        _run_cli(None, tmp_env, ["uninstall"], mock_pw="wrong" * 5)
    assert tmp_env["config"].exists()
    # Correct should remove
    _run_cli(None, tmp_env, ["uninstall"], mock_pw=pw)
    assert not tmp_env["config"].exists()


def test_block_custom_arbitrary_sites(tmp_env, monkeypatch):
    # user can block any site, not just suggested list
    pw = "d" * 20
    with patch("builtins.input", return_value=""):
        _run_cli(None, tmp_env, ["setup", "--password", pw])
    # block arbitrary custom domains not in SUGGESTED_SITES
    custom1 = "mycustom12345.com"
    custom2 = "example.org"
    custom3 = "whatever.someone.invents.example.com"
    # need dnsmasq mock for wildcard check
    monkeypatch.setenv("KEEP_FOCUSED_DNSMASQ", str(tmp_env["tmp"] / "dnsmasq_custom.conf"))
    _run_cli(None, tmp_env, ["block", custom1, custom2], mock_pw=pw)
    data = json.loads(tmp_env["config"].read_text())
    assert custom1 in data["blocked_sites"]
    assert custom2 in data["blocked_sites"]
    # hosts should have them
    hosts_content = tmp_env["hosts"].read_text()
    assert custom1 in hosts_content
    assert custom2 in hosts_content
    # dnsmasq wildcard and is_blocked_host should cover any depth
    from keep_focused.hosts import is_blocked_host
    from keep_focused.dnsmasq import get_dnsmasq_blocked

    assert custom1 in get_dnsmasq_blocked()
    assert is_blocked_host(f"a.b.c.{custom1}", [custom1])
    assert is_blocked_host(f"andy.whatever.someone.invents.{custom2}", [custom2])
    # block another custom with subdomain
    _run_cli(None, tmp_env, ["block", custom3], mock_pw=pw)
    data = json.loads(tmp_env["config"].read_text())
    assert custom3 in data["blocked_sites"]
