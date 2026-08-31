"""dnsmasq wildcard blocking – any subdomain of blocked domain is blocked.

Hosts file has no wildcard, so `spotify.com` only blocks bare+www.
dnsmasq `address=/domain/127.0.0.1` blocks domain and *.<domain> with suffix
dot handling (not infix): open.spotify.com → blocked, notspotify.com → not.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .hosts import normalize_domain

DNSMASQ_CONF_PATH = Path("/etc/dnsmasq.d/keep-focused.conf")
ALT_CONF_PATH = Path("/etc/dnsmasq.conf.d/keep-focused.conf")
MARKER = "# keep-focused dnsmasq wildcard"


def _dnsmasq_path() -> Path | None:
    env = os.environ.get("KEEP_FOCUSED_DNSMASQ")
    if env:
        return Path(env)
    # prefer /etc/dnsmasq.d if exists or can be created, else alt
    for p in (DNSMASQ_CONF_PATH, ALT_CONF_PATH):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.parent.exists():
                return p
        except Exception:
            continue
    return DNSMASQ_CONF_PATH


def _build_dnsmasq_conf(domains: list[str]) -> str:
    if not domains:
        return f"{MARKER} empty\n"
    lines = [MARKER]
    for raw in domains:
        d = normalize_domain(raw)
        if not d or "." not in d:
            continue
        # dnsmasq address handles suffix wildcard for any depth:
        # address=/spotify.com/127.0.0.1 blocks spotify.com and *.spotify.com
        lines.append(f"address=/{d}/127.0.0.1")
        lines.append(f"address=/{d}/::1")
    lines.append(MARKER)
    return "\n".join(lines) + "\n"


def _write_with_sudo(content: str, path: Path) -> bool:
    # try direct
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content)
        tmp.replace(path)
        return True
    except PermissionError:
        pass
    except OSError as e:
        if "Permission denied" in str(e) or getattr(e, "errno", None) == 13:
            pass
        else:
            return False
    if shutil.which("sudo"):
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as tf:
                tf.write(content)
                tmp_name = tf.name
            result = subprocess.run(
                ["sudo", "tee", str(path)],
                input=content,
                text=True,
                capture_output=True,
                check=False,
            )
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except Exception:
                pass
            return result.returncode == 0
        except Exception:
            return False
    if shutil.which("pkexec"):
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as tf:
                tf.write(content)
                tmp_name = tf.name
            result = subprocess.run(
                ["pkexec", "cp", tmp_name, str(path)], capture_output=True, check=False
            )
            Path(tmp_name).unlink(missing_ok=True)
            return result.returncode == 0
        except Exception:
            return False
    return False


def _restart_dnsmasq() -> bool:
    for cmd in (
        ["sudo", "systemctl", "restart", "dnsmasq"],
        ["sudo", "service", "dnsmasq", "restart"],
        ["sudo", "pkexec", "systemctl", "restart", "dnsmasq"],
        ["systemctl", "restart", "dnsmasq"],
    ):
        try:
            result = subprocess.run(cmd, capture_output=True, check=False, timeout=10)
            if result.returncode == 0:
                return True
        except Exception:
            continue
    # try HUP
    for cmd in (["sudo", "pkill", "-HUP", "dnsmasq"], ["pkill", "-HUP", "dnsmasq"]):
        try:
            result = subprocess.run(cmd, capture_output=True, check=False, timeout=5)
            if result.returncode == 0:
                return True
        except Exception:
            continue
    return False


def _is_dnsmasq_installed() -> bool:
    return shutil.which("dnsmasq") is not None


def apply_dnsmasq_block(domains: list[str], enabled: bool = True) -> bool:
    """Write dnsmasq wildcard conf. Returns True if active, False if fallback to hosts."""
    path = _dnsmasq_path()
    if path is None:
        return False
    # use env override for tests -> don't need real dnsmasq
    if os.environ.get("KEEP_FOCUSED_DNSMASQ"):
        content = _build_dnsmasq_conf(domains if enabled else [])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return True
        except Exception:
            return False

    if not _is_dnsmasq_installed():
        # try to keep hosts fallback; don't fail
        return False

    content = _build_dnsmasq_conf(domains if enabled else [])
    if not _write_with_sudo(content, path):
        return False
    _restart_dnsmasq()
    return True


def clear_dnsmasq_block() -> bool:
    return apply_dnsmasq_block([], enabled=False)


def get_dnsmasq_blocked() -> list[str]:
    path = _dnsmasq_path()
    if path is None or not path.exists():
        return []
    try:
        content = path.read_text()
    except PermissionError:
        if shutil.which("sudo"):
            try:
                result = subprocess.run(
                    ["sudo", "cat", str(path)], capture_output=True, text=True, check=False
                )
                if result.returncode == 0:
                    content = result.stdout
                else:
                    return []
            except Exception:
                return []
        else:
            return []
    domains = []
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("address=/"):
            # address=/domain/127.0.0.1
            m = re.match(r"address=/([^/]+)/", line)
            if m:
                domains.append(m.group(1))
    return sorted(set(domains))


def is_dnsmasq_active() -> bool:
    return len(get_dnsmasq_blocked()) > 0
