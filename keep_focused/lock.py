"""File locking via chattr +i – best-effort, to prevent manual bypass without password."""

import shutil
import subprocess
from pathlib import Path


def _has_chattr() -> bool:
    return shutil.which("chattr") is not None and shutil.which("lsattr") is not None


def is_immutable(path: Path) -> bool:
    if not _has_chattr() or not path.exists():
        return False
    try:
        result = subprocess.run(
            ["lsattr", str(path)], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0 and result.stdout:
            # lsattr output starts with attributes, e.g., "----i---------e------- ./file"
            attrs = result.stdout.split()[0] if result.stdout.split() else ""
            return "i" in attrs
    except Exception:
        pass
    return False


def _run_chattr(path: Path, lock: bool) -> bool:
    if not _has_chattr():
        return False
    flag = "+i" if lock else "-i"
    # Try direct (if root or owner and filesystem supports)
    try:
        result = subprocess.run(
            ["chattr", flag, str(path)], capture_output=True, timeout=2
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass
    # Try via sudo if available (for /etc/hosts, system config)
    if shutil.which("sudo"):
        try:
            result = subprocess.run(
                ["sudo", "chattr", flag, str(path)], capture_output=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            pass
    # Try pkexec as last resort
    if shutil.which("pkexec"):
        try:
            result = subprocess.run(
                ["pkexec", "chattr", flag, str(path)], capture_output=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            pass
    return False


def lock_file(path: Path) -> bool:
    """Make file immutable (best-effort). Returns True if locked or chattr not available (treated as success)."""
    if not path.exists():
        return False
    # If chattr not available, just chmod 600/400 as fallback
    if not _has_chattr():
        try:
            path.chmod(0o600)
        except Exception:
            pass
        return True
    # If already immutable, success
    if is_immutable(path):
        return True
    return _run_chattr(path, lock=True)


def unlock_file(path: Path) -> bool:
    """Make file mutable. Returns True if unlocked or chattr not available."""
    if not path.exists():
        return True
    if not _has_chattr():
        return True
    if not is_immutable(path):
        return True
    return _run_chattr(path, lock=False)
