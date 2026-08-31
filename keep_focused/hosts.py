"""Hosts-file blocking – system-wide, works for Chrome/Firefox/etc."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HOSTS_PATH = Path("/etc/hosts")
BEGIN_MARKER = "# BEGIN keep-focused"
END_MARKER = "# END keep-focused"

IPV4 = "127.0.0.1"
IPV6 = "::1"


def _hosts_path() -> Path:
    env = os.environ.get("KEEP_FOCUSED_HOSTS")
    if env:
        return Path(env)
    return HOSTS_PATH


def normalize_domain(domain: str) -> str:
    """Lowercase, strip scheme/path/port, strip leading 'www.'."""
    d = domain.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0]
    d = d.split(":")[0]
    d = d.lstrip(".")
    if d.startswith("www."):
        d = d[4:]
    return d


def expand_domains(domains: list[str]) -> list[str]:
    """For each domain, also block www. variant. Deduplicate, sorted."""
    out: set[str] = set()
    for raw in domains:
        d = normalize_domain(raw)
        if not d or "." not in d:
            continue
        out.add(d)
        out.add(f"www.{d}")
    return sorted(out)


def _build_block_section(domains: list[str]) -> str:
    if not domains:
        return ""
    expanded = expand_domains(domains)
    lines = [BEGIN_MARKER]
    for d in expanded:
        lines.append(f"{IPV4} {d}")
        lines.append(f"{IPV6} {d}")
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def read_hosts() -> str:
    p = _hosts_path()
    if not p.exists():
        return ""
    try:
        return p.read_text()
    except PermissionError:
        # Try via sudo cat if needed
        if shutil.which("sudo"):
            try:
                result = subprocess.run(
                    ["sudo", "cat", str(p)], capture_output=True, text=True, check=False
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass
        raise


def _write_hosts_direct(content: str, path: Path) -> None:
    """Attempt direct write; raise PermissionError if not allowed."""
    # Check if we can write
    try:
        # Use atomic write via temp
        tmp = path.with_suffix(".tmp")
        # For testing with custom hosts path, just write
        # For /etc/hosts, this will fail if not root
        tmp.write_text(content)
        tmp.replace(path)
        return
    except PermissionError:
        raise
    except OSError as e:
        if "Permission denied" in str(e) or e.errno == 13:
            raise PermissionError(str(e)) from e
        raise


def _write_hosts_with_sudo(content: str, path: Path) -> bool:
    """Try to write hosts via sudo tee. Returns True on success."""
    if not shutil.which("sudo"):
        return False
    # Use sudo tee with a temp file
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tf:
            tf.write(content)
            tf.flush()
            tmp_name = tf.name
        # Use sudo to move temp into place
        # We use `sudo tee` to handle permission
        result = subprocess.run(
            ["sudo", "tee", str(path)],
            input=content,
            text=True,
            capture_output=True,
            check=False,
        )
        # Clean up tmp if exists
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except Exception:
            pass
        return result.returncode == 0
    except Exception:
        return False


def write_hosts(content: str) -> None:
    p = _hosts_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # If custom path for tests, just write directly (no sudo needed)
    if os.environ.get("KEEP_FOCUSED_HOSTS"):
        # Testing: direct write
        tmp = p.with_suffix(".tmp")
        tmp.write_text(content)
        tmp.replace(p)
        return

    # Try direct write first (works if running as root or hosts is writable)
    try:
        _write_hosts_direct(content, p)
        return
    except PermissionError:
        pass

    # Fall back to sudo
    # Check if sudo is available and we can escalate
    if _write_hosts_with_sudo(content, p):
        return

    # Try pkexec as last resort (GUI)
    if shutil.which("pkexec"):
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".hosts") as tf:
                tf.write(content)
                tmp_name = tf.name
            result = subprocess.run(
                ["pkexec", "cp", tmp_name, str(p)], capture_output=True, check=False
            )
            Path(tmp_name).unlink(missing_ok=True)
            if result.returncode == 0:
                return
        except Exception:
            pass

    raise PermissionError(
        f"Permission denied writing {p}. Try running with sudo: sudo keep-focused"
    )


def _strip_existing_block(content: str) -> str:
    """Remove existing keep-focused block (between markers)."""
    pattern = re.compile(
        rf"{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?",
        re.DOTALL,
    )
    stripped = pattern.sub("", content)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped


def apply_block(domains: list[str], enabled: bool = True) -> None:
    """Apply blocking state to hosts file."""
    content = read_hosts()
    content = _strip_existing_block(content)
    if enabled and domains:
        block = _build_block_section(domains)
        if content and not content.endswith("\n"):
            content += "\n"
        content += block
    write_hosts(content)


def clear_block() -> None:
    """Remove all keep-focused entries from hosts."""
    content = read_hosts()
    content = _strip_existing_block(content)
    write_hosts(content)


def get_blocked_from_hosts() -> list[str]:
    """Parse currently blocked domains from hosts file."""
    try:
        content = read_hosts()
    except PermissionError:
        return []
    m = re.search(rf"{re.escape(BEGIN_MARKER)}(.*?){re.escape(END_MARKER)}", content, re.DOTALL)
    if not m:
        return []
    block = m.group(1)
    domains: set[str] = set()
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        for d in parts[1:]:
            d = d.strip()
            if d:
                domains.add(d)
    return sorted(domains)


def is_block_active() -> bool:
    return len(get_blocked_from_hosts()) > 0
