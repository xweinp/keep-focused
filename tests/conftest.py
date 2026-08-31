"""Shared fixtures for keep-focused tests – all use temp files, never touch real /etc/hosts."""

import os
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    """Isolate config/hosts/service to temp files."""
    hosts = tmp_path / "hosts"
    config = tmp_path / "config.json"
    service = tmp_path / "service"
    hosts.write_text("127.0.0.1 localhost\n::1 localhost\n")
    monkeypatch.setenv("KEEP_FOCUSED_HOSTS", str(hosts))
    monkeypatch.setenv("KEEP_FOCUSED_CONFIG", str(config))
    monkeypatch.setenv("KEEP_FOCUSED_SERVICE", str(service))
    # Isolate XDG/HOME so fallback to ~/.config doesn't find real config
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("HOME", str(tmp_path))
    # Ensure arrow navigation disabled for most tests (they mock input)
    monkeypatch.delenv("KEEP_FOCUSED_ARROW", raising=False)
    monkeypatch.setenv("KEEP_FOCUSED_NO_ARROW", "1")
    # Clear any existing real config from previous runs
    return {"hosts": hosts, "config": config, "service": service, "tmp": tmp_path}


@pytest.fixture()
def tmp_env_arrow(tmp_path, monkeypatch):
    """Same but with arrow navigation enabled (for arrow tests)."""
    hosts = tmp_path / "hosts"
    config = tmp_path / "config.json"
    service = tmp_path / "service"
    hosts.write_text("127.0.0.1 localhost\n")
    monkeypatch.setenv("KEEP_FOCUSED_HOSTS", str(hosts))
    monkeypatch.setenv("KEEP_FOCUSED_CONFIG", str(config))
    monkeypatch.setenv("KEEP_FOCUSED_SERVICE", str(service))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KEEP_FOCUSED_ARROW", "1")
    monkeypatch.delenv("KEEP_FOCUSED_NO_ARROW", raising=False)
    # Mock isatty to True for arrow tests
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    return {"hosts": hosts, "config": config, "service": service, "tmp": tmp_path}
