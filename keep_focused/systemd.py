"""Systemd integration – ensures blocking is re-applied on boot.

Handles both system service (/etc/systemd/system) when running as root/sudo,
and user service (~/.config/systemd/user) for no-sudo installs like opencode/claude.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "keep-focused.service"
SYSTEMD_PATH = Path("/etc/systemd/system") / SERVICE_NAME


def _user_service_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / "systemd" / "user" / SERVICE_NAME


def _service_path(prefer_user: bool | None = None) -> Path:
    env = os.environ.get("KEEP_FOCUSED_SERVICE")
    if env:
        return Path(env)
    # Auto-detect: prefer user service if not root and user service exists, else system
    if prefer_user is None:
        try:
            is_root = os.geteuid() == 0
        except AttributeError:
            is_root = False
        if not is_root and _user_service_path().exists():
            return _user_service_path()
        if is_root:
            return SYSTEMD_PATH
        # For non-root without existing user service, we will try system first via sudo, fallback to user
        # Default to user for no-sudo install
        return _user_service_path()
    return _user_service_path() if prefer_user else SYSTEMD_PATH


def _find_executable() -> str:
    exe = shutil.which("keep-focused")
    if exe:
        return exe
    return f"{sys.executable} -m keep_focused"


def service_content(executable: str | None = None) -> str:
    if executable is None:
        executable = _find_executable()
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


def _user_systemd_available() -> bool:
    return shutil.which("systemctl") is not None


def is_systemd_available() -> bool:
    # System service requires /run/systemd/system, user service just needs systemctl
    if shutil.which("systemctl") is None:
        return False
    # If we're checking for user service, it's enough that systemctl exists
    # For system service, check /run/systemd/system
    return True


def _try_system_service_install(content: str, executable: str) -> bool:
    """Try to install system service via sudo if not root."""
    path = SYSTEMD_PATH
    try:
        # If running as root, direct write
        if os.geteuid() == 0:
            path.write_text(content)
            path.chmod(0o644)
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            subprocess.run(["systemctl", "enable", SERVICE_NAME], check=False)
            subprocess.run(["systemctl", "start", SERVICE_NAME], check=False)
            return True
    except Exception:
        pass

    # Try via sudo
    if shutil.which("sudo"):
        try:
            # Write to temp and sudo move
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", delete=False) as tf:
                tf.write(content)
                tmp = tf.name
            result = subprocess.run(
                ["sudo", "tee", str(path)], input=content, text=True, capture_output=True, check=False
            )
            Path(tmp).unlink(missing_ok=True)
            if result.returncode == 0:
                subprocess.run(["sudo", "systemctl", "daemon-reload"], check=False)
                subprocess.run(["sudo", "systemctl", "enable", SERVICE_NAME], check=False)
                subprocess.run(["sudo", "systemctl", "start", SERVICE_NAME], check=False)
                return True
        except Exception as e:
            print(f"  ! sudo system service install failed: {e}")
    return False


def _install_user_service(content: str) -> bool:
    path = _user_service_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o644)
        # Enable user service
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], check=False)
        # Enable linger so it runs on boot even without login (if loginctl available)
        if shutil.which("loginctl"):
            subprocess.run(["loginctl", "enable-linger", os.environ.get("USER", "")], check=False)
        return True
    except Exception as e:
        print(f"  ! Failed to install user systemd service: {e}")
        return False


def install_service() -> bool:
    """Write service file and enable it. Works without sudo (user service) or with sudo (system service)."""
    if os.environ.get("KEEP_FOCUSED_SERVICE"):
        p = _service_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(service_content())
        return True

    if not _user_systemd_available():
        return False

    executable = _find_executable()
    content = service_content(executable)

    # Try system service first (preferred: works before login, no sudo needed at boot)
    # If we are root or sudo is available, this will succeed
    if _try_system_service_install(content, executable):
        return True

    # Fall back to user service (no sudo needed)
    if _install_user_service(content):
        print("  → Installed user service at", _user_service_path())
        print("    (system service not installed – will need sudo password at setup, but runs on user login)")
        return True

    return False


def uninstall_service() -> bool:
    """Remove both system and user services if they exist."""
    success = True
    for prefer_user in [False, True]:
        p = _service_path(prefer_user=prefer_user)
        # Also handle env override
        if os.environ.get("KEEP_FOCUSED_SERVICE"):
            p = Path(os.environ["KEEP_FOCUSED_SERVICE"])
        try:
            if p.exists():
                if prefer_user:
                    subprocess.run(["systemctl", "--user", "disable", SERVICE_NAME], check=False)
                    subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], check=False)
                else:
                    # Try with sudo if not root
                    try:
                        if os.geteuid() == 0:
                            subprocess.run(["systemctl", "disable", SERVICE_NAME], check=False)
                            subprocess.run(["systemctl", "stop", SERVICE_NAME], check=False)
                        elif shutil.which("sudo"):
                            subprocess.run(["sudo", "systemctl", "disable", SERVICE_NAME], check=False)
                            subprocess.run(["sudo", "systemctl", "stop", SERVICE_NAME], check=False)
                        else:
                            subprocess.run(["systemctl", "disable", SERVICE_NAME], check=False)
                    except Exception:
                        pass
                    # Remove file via sudo if needed
                    try:
                        p.unlink()
                    except PermissionError:
                        if shutil.which("sudo"):
                            subprocess.run(["sudo", "rm", "-f", str(p)], check=False)
                        else:
                            raise
                    else:
                        if not os.environ.get("KEEP_FOCUSED_SERVICE"):
                            try:
                                subprocess.run(
                                    ["sudo", "systemctl", "daemon-reload"] if shutil.which("sudo") else ["systemctl", "daemon-reload"],
                                    check=False,
                                )
                            except Exception:
                                pass
                    continue

                p.unlink(missing_ok=True)
                if prefer_user:
                    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
                else:
                    subprocess.run(["systemctl", "daemon-reload"], check=False)
        except Exception as e:
            print(f"  ! Failed to remove systemd service {p}: {e}")
            success = False
        # Only one iteration if env override
        if os.environ.get("KEEP_FOCUSED_SERVICE"):
            break
    return success


def is_service_enabled() -> bool:
    if os.environ.get("KEEP_FOCUSED_SERVICE"):
        return Path(os.environ["KEEP_FOCUSED_SERVICE"]).exists()
    # Check both system and user
    for prefer_user in [False, True]:
        p = _service_path(prefer_user=prefer_user)
        if p.exists():
            return True
        # Also check systemctl is-enabled
        if prefer_user:
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", SERVICE_NAME],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True
        else:
            # Need to handle sudo/system check
            result = subprocess.run(
                ["systemctl", "is-enabled", SERVICE_NAME],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True
    return False


def service_location() -> Path | None:
    """Return path of installed service if any."""
    if os.environ.get("KEEP_FOCUSED_SERVICE"):
        p = Path(os.environ["KEEP_FOCUSED_SERVICE"])
        return p if p.exists() else None
    for prefer_user in [False, True]:
        p = _service_path(prefer_user=prefer_user)
        if p.exists():
            return p
    return None
