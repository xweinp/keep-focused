"""Config persistence – /etc/keep-focused/config.json (system-wide)."""

import json
import os
from pathlib import Path

CONFIG_DIR = Path("/etc/keep-focused")
CONFIG_FILE = CONFIG_DIR / "config.json"

# For testing / non-root dev: allow override via env
def _config_path() -> Path:
    env = os.environ.get("KEEP_FOCUSED_CONFIG")
    if env:
        return Path(env)
    return CONFIG_FILE


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_config() -> dict | None:
    p = _config_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_config(cfg: dict) -> None:
    p = _config_path()
    _ensure_dir(p)
    # Write atomically
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
