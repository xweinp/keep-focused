"""Config persistence – user-local ~/.config/keep-focused/config.json with /etc fallback."""

import json
import os
from pathlib import Path

# System-wide (legacy / when running as root)
SYSTEM_CONFIG_DIR = Path("/etc/keep-focused")
SYSTEM_CONFIG_FILE = SYSTEM_CONFIG_DIR / "config.json"

# User-local (preferred for no-sudo install, like opencode/claude)
def _user_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "keep-focused" / "config.json"
    return Path.home() / ".config" / "keep-focused" / "config.json"


def _config_path() -> Path:
    # 1. Explicit override for testing
    env = os.environ.get("KEEP_FOCUSED_CONFIG")
    if env:
        return Path(env)
    # 2. If system config exists and user config does not, prefer system (migration/backwards compat)
    #    Also if running as root and system config exists
    sys_path = SYSTEM_CONFIG_FILE
    user_path = _user_config_path()
    # If system config exists, use it when:
    # - user config does not exist, OR running as root (uid 0)
    try:
        is_root = os.geteuid() == 0
    except AttributeError:
        is_root = False
    if sys_path.exists():
        if not user_path.exists() or is_root:
            return sys_path
    # 3. Otherwise use user config
    return user_path


def _all_config_paths() -> list[Path]:
    """Return all possible config locations (for uninstall/cleanup)."""
    paths = [_user_config_path(), SYSTEM_CONFIG_FILE]
    env = os.environ.get("KEEP_FOCUSED_CONFIG")
    if env:
        paths.insert(0, Path(env))
    return paths


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_config() -> dict | None:
    # Try primary path first, then fallback to the other location
    primary = _config_path()
    candidates = [primary] + [p for p in _all_config_paths() if p != primary]
    for p in candidates:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                # If we loaded from fallback, remember it but return it
                return data
            except (json.JSONDecodeError, OSError):
                continue
    return None


def _actual_save_path() -> Path:
    """Path where save_config will write (primary)."""
    return _config_path()


def save_config(cfg: dict) -> None:
    p = _actual_save_path()
    _ensure_dir(p)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n")
    tmp.chmod(0o600)
    tmp.replace(p)
    try:
        p.chmod(0o600)
    except OSError:
        pass


def is_setup() -> bool:
    cfg = load_config()
    return cfg is not None and "password_hash" in cfg


def default_config(password_hash: str, salt: str, blocked_sites: list[str]) -> dict:
    return {
        "password_hash": password_hash,
        "salt": salt,
        "blocked_sites": sorted(set(s.strip().lower() for s in blocked_sites if s.strip())),
        "enabled": True,
        "version": 1,
    }


def config_location() -> Path:
    """Public helper for UI to show where config lives."""
    return _config_path()
