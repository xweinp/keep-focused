"""Shared fixtures for keep-focused tests – all use temp files, never touch real /etc/hosts."""

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
    # Clear any existing real config from previous runs
    return {"hosts": hosts, "config": config, "service": service, "tmp": tmp_path}

