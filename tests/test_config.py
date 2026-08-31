import json
import os
from pathlib import Path

import keep_focused.config as cfg_mod
from keep_focused.auth import hash_password
from keep_focused.config import config_location, default_config, load_config, save_config


def test_save_and_load(tmp_env):
    pw = "a" * 20
    salt, h = hash_password(pw)
    cfg = default_config(h, salt, ["facebook.com", "x.com"])
    save_config(cfg)
    loaded = load_config()
    assert loaded["blocked_sites"] == ["facebook.com", "x.com"]
    assert loaded["password_hash"] == h
    assert loaded["enabled"] is True
    assert config_location().exists()


def test_config_user_vs_system(tmp_path, monkeypatch):
    # Without env override, user config is ~/.config – but in test we use tmp_env
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n")
    monkeypatch.setenv("KEEP_FOCUSED_HOSTS", str(hosts))
    # No config yet
    cfg_path = tmp_path / "myconfig.json"
    monkeypatch.setenv("KEEP_FOCUSED_CONFIG", str(cfg_path))
    import importlib, keep_focused.config as cfgm

    importlib.reload(cfgm)
    assert not cfgm.load_config()
    pw = "y" * 20
    salt, h = hash_password(pw)
    cfgm.save_config(cfgm.default_config(h, salt, ["example.com"]))
    assert cfgm.load_config()["blocked_sites"] == ["example.com"]


def test_config_preserves_sort_and_lowercase(tmp_env):
    pw = "a" * 20
    salt, h = hash_password(pw)
    cfg = default_config(h, salt, ["Facebook.COM", "X.COM", "facebook.com"])
    # Should deduplicate and sort lowercased
    assert cfg["blocked_sites"] == ["facebook.com", "x.com"]
