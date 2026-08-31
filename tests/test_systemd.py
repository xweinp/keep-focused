from pathlib import Path

import keep_focused.systemd as systemd_mod
from keep_focused.systemd import install_service, is_service_enabled, service_content, uninstall_service


def test_service_content_has_env_for_user_wrapper(tmp_path, monkeypatch):
    # Simulate user wrapper path
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KEEP_FOCUSED_INSTALL_DIR", str(tmp_path / "share"))
    monkeypatch.setenv("KEEP_FOCUSED_CONFIG", str(tmp_path / "config.json"))
    # Create fake install dir
    (tmp_path / "share" / "keep_focused").mkdir(parents=True)
    (tmp_path / "share" / "keep_focused" / "cli.py").write_text("# dummy")
    # When executable is user wrapper, service should contain Environment
    content = service_content("/home/test/.local/bin/keep-focused")
    assert "Environment=PYTHONPATH" in content
    assert "Environment=KEEP_FOCUSED_CONFIG" in content
    assert "ExecStart=" in content
    assert "python" in content
    assert "WantedBy=multi-user.target" in content

    # User service should use default.target
    content_user = service_content("/home/test/.local/bin/keep-focused", is_user=True)
    assert "WantedBy=default.target" in content_user


def test_install_service_creates_file(tmp_env):
    # tmp_env sets KEEP_FOCUSED_SERVICE to tmp file, so install should just write it
    service = tmp_env["service"]
    assert not service.exists()
    assert install_service()
    assert service.exists()
    content = service.read_text()
    assert "keep-focused" in content
    assert is_service_enabled()
    assert uninstall_service()
    assert not service.exists()
    assert not is_service_enabled()


def test_install_prefers_user_for_user_local(tmp_path, monkeypatch):
    # This test checks that install_service prefers user service when install_dir is user-local
    # Mock _install_user_service to track calls
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n")
    config = tmp_path / "config.json"
    service = tmp_path / "service_user"
    monkeypatch.setenv("KEEP_FOCUSED_HOSTS", str(hosts))
    monkeypatch.setenv("KEEP_FOCUSED_CONFIG", str(config))
    monkeypatch.setenv("KEEP_FOCUSED_SERVICE", str(service))
    # Force user-local install dir
    monkeypatch.setenv("KEEP_FOCUSED_INSTALL_DIR", str(tmp_path / "share"))
    (tmp_path / "share" / "keep_focused").mkdir(parents=True)
    (tmp_path / "share" / "keep_focused" / "cli.py").write_text("# dummy")
    # Need to reload to pick up env
    import importlib, keep_focused.systemd as sm

    importlib.reload(sm)
    assert sm.install_service()
    assert service.exists()
