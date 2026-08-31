"""Hosts-file blocking – system-wide, works for Chrome/Firefox/etc."""

import os
import re
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
    # remove scheme
    d = re.sub(r"^https?://", "", d)
    # remove path/query/fragment
    d = d.split("/")[0].split("?")[0].split("#")[0]
    # remove port
    d = d.split(":")[0]
    # strip leading dot
    d = d.lstrip(".")
    # strip leading www. for canonical storage (expand will add it back)
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
        # For x.com ↔ twitter.com alias, don't auto-expand; user controls.
    return sorted(out)


def _build_block_section(domains: list[str]) -> str:
    if not domains:
        return ""
    expanded = expand_domains(domains)
    lines = [BEGIN_MARKER]
    # group per IP to keep file tidy – one line per domain per IP
    for d in expanded:
        lines.append(f"{IPV4} {d}")
        lines.append(f"{IPV6} {d}")
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def read_hosts() -> str:
    p = _hosts_path()
    if not p.exists():
        return ""
    return p.read_text()


def write_hosts(content: str) -> None:
    p = _hosts_path()
    # Ensure parent exists
    p.parent.mkdir(parents=True, exist_ok=True)
    # Preserve permissions if exists
    tmp = p.with_suffix(".tmp")
    tmp.write_text(content)
    tmp.replace(p)


def _strip_existing_block(content: str) -> str:
    """Remove existing keep-focused block (between markers)."""
    pattern = re.compile(
        rf"{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?",
        re.DOTALL,
    )
    stripped = pattern.sub("", content)
    # Clean up excessive blank lines (max 2 newlines)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped


def apply_block(domains: list[str], enabled: bool = True) -> None:
    """Apply blocking state to hosts file."""
    content = read_hosts()
    content = _strip_existing_block(content)
    if enabled and domains:
        block = _build_block_section(domains)
        # Ensure trailing newline before appending
        if content and not content.endswith("\n"):
            content += "\n"
        content += block
    # If disabled or empty, we just leave stripped content
    write_hosts(content)


def clear_block() -> None:
    """Remove all keep-focused entries from hosts."""
    content = read_hosts()
    content = _strip_existing_block(content)
    write_hosts(content)


def get_blocked_from_hosts() -> list[str]:
    """Parse currently blocked domains from hosts file."""
    content = read_hosts()
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
        # parts[0] is IP, rest are domains
        for d in parts[1:]:
            d = d.strip()
            if d:
                domains.add(d)
    return sorted(domains)


def is_block_active() -> bool:
    return len(get_blocked_from_hosts()) > 0
