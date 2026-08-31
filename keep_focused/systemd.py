"""Systemd integration – ensure blocking is re-applied on boot."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "keep-focused.service"
SYSTEMD_PATH = Path("/etc/systemd/system") / SERVICE_NAME


def _service_path() -> Path:
    env = os.environ.get("KEEP_FOCUSED_SERVICE")
    if env:
        return Path(env)
    return SYSTEMD_PATH


def _find_executable() -> str:
    exe = shutil.which("keep-focused")
    if exe:
        return exe
    # fallback to current python -m
    return f"{sys.executable} -m keep_focused.cli"


def service_content(executable: str | None = None) -> str:
    if executable is None:
        executable = _find_executable()
    # If executable contains spaces (python -m), handle accordingly
    if " " in executable:
        exec_start = executable + " apply"
    else:
        exec_start = f"{executable} apply"
    return f"""[Unit]
Description=keep-focused – re-apply website blocks on boot
After=network.target

[Service]
Type=oneshot
ExecStart={exec_start}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""


def is_systemd_available() -> bool:
    return shutil.which("systemctl") is not None and Path("/run/systemd/system").exists()


def install_service() -> bool:
    """Write service file and enable it. Returns True on success."""
    if os.environ.get("KEEP_FOCUSED_SERVICE"):
        # Testing: just write file, no systemctl
        p = _service_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(service_content())
        return True

    if not is_systemd_available():
        return False

    executable = _find_executable()
    content = service_content(executable)
    try:
        p = _service_path()
        p.write_text(content)
        p.chmod(0o644)
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "enable", SERVICE_NAME], check=False)
        # Also start it now (apply already done, but ensure state)
        subprocess.run(["systemctl", "start", SERVICE_NAME], check=False)
        return True
    except PermissionError:
        print("  ! Need root to install systemd service. Run with sudo.")
        return False
    except Exception as e:
        print(f"  ! Failed to install systemd service: {e}")
        return False


def uninstall_service() -> bool:
    p = _service_path()
    try:
        if p.exists():
            if is_systemd_available() and not os.environ.get("KEEP_FOCUSED_SERVICE"):
                subprocess.run(["systemctl", "disable", SERVICE_NAME], check=False)
                subprocess.run(["systemctl", "stop", SERVICE_NAME], check=False)
            p.unlink()
            if is_systemd_available() and not os.environ.get("KEEP_FOCUSED_SERVICE"):
                subprocess.run(["systemctl", "daemon-reload"], check=False)
        return True
    except Exception as e:
        print(f"  ! Failed to remove systemd service: {e}")
        return False


def is_service_enabled() -> bool:
    if os.environ.get("KEEP_FOCUSED_SERVICE"):
        return _service_path().exists()
    if not is_systemd_available():
        return _service_path().exists()
    result = subprocess.run(
        ["systemctl", "is-enabled", SERVICE_NAME],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
