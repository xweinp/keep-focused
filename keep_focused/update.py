"""Self-update for keep-focused – no sudo, no pip, like opencode."""

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from . import __version__

REPO = os.environ.get("KEEP_FOCUSED_REPO", "https://github.com/xweinp/keep-focused")
RAW_BASE = REPO.replace("https://github.com", "https://raw.githubusercontent.com")
# Handle case where REPO is git@github.com:... or https://
if RAW_BASE == REPO and REPO.startswith("git@"):
    RAW_BASE = "https://raw.githubusercontent.com/xweinp/keep-focused"


def _current_install_dir() -> Path:
    # Wrapper sets KEEP_FOCUSED_INSTALL_DIR, else default
    env = os.environ.get("KEEP_FOCUSED_INSTALL_DIR")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "keep-focused"


def _find_repo_root() -> Path | None:
    """Find git repo root if running from a checkout (has .git)."""
    # This file is keep_focused/update.py -> parent is keep_focused, grandparent is repo root
    try:
        current = Path(__file__).resolve()
        for parent in [current.parent.parent, current.parent, Path.cwd()]:
            if (parent / ".git").exists() and (parent / "keep_focused" / "cli.py").exists():
                return parent
        # Also check install dir's parent maybe has .git? No, install dir is copy without .git
        # Check for git available and cwd is repo
        cwd = Path.cwd()
        if (cwd / ".git").exists() and (cwd / "keep_focused" / "cli.py").exists():
            return cwd
    except Exception:
        pass
    return None


def _fetch_remote_version() -> str | None:
    """Fetch remote __version__ via raw GitHub."""
    url = f"{RAW_BASE}/main/keep_focused/__init__.py"
    # Also try master branch fallback
    urls = [url, url.replace("/main/", "/master/")]
    for u in urls:
        try:
            with urllib.request.urlopen(u, timeout=5) as resp:
                data = resp.read().decode("utf-8", errors="ignore")
                for line in data.splitlines():
                    line = line.strip()
                    if line.startswith("__version__"):
                        parts = line.split("=")
                        if len(parts) == 2:
                            v = parts[1].strip().strip('"').strip("'")
                            return v
        except Exception:
            continue
    return None


def _update_via_git(repo_root: Path) -> bool:
    """Try git pull in repo_root. Returns True if success."""
    if not shutil.which("git"):
        return False
    try:
        print(f"  → git pull in {repo_root}")
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(result.stdout.strip())
        if result.stderr:
            print(result.stderr.strip())
        return result.returncode == 0
    except Exception as e:
        print(f"  ! git pull failed: {e}")
        return False


def _update_via_install_sh() -> bool:
    """Download and run install.sh via bash (like curl | bash), but using Python to avoid curl dep."""
    # We will fetch install.sh content and execute it
    install_url = f"{RAW_BASE}/main/install.sh"
    urls = [install_url, install_url.replace("/main/", "/master/")]
    install_content = None
    used_url = None
    for u in urls:
        try:
            with urllib.request.urlopen(u, timeout=10) as resp:
                install_content = resp.read()
                used_url = u
                break
        except Exception as e:
            print(f"  ! fetch {u} failed: {e}")
            continue
    if install_content is None:
        print("  ! Could not fetch install.sh from GitHub.")
        return False

    print(f"  → fetched install.sh from {used_url} ({len(install_content)} bytes)")

    # Write to temp and execute with bash
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".sh", delete=False) as tf:
        tf.write(install_content)
        tf_name = tf.name
    try:
        os.chmod(tf_name, 0o755)
        # Run with bash, inherit env and pass through
        env = os.environ.copy()
        # Ensure install knows it's an update
        env["KEEP_FOCUSED_UPDATE"] = "1"
        result = subprocess.run(["bash", tf_name], env=env)
        return result.returncode == 0
    except Exception as e:
        print(f"  ! install.sh execution failed: {e}")
        return False
    finally:
        try:
            Path(tf_name).unlink(missing_ok=True)
        except Exception:
            pass


def perform_update(check_only: bool = False, force: bool = False) -> int:
    """Main update logic. Returns 0 on success, 1 on failure."""
    # Colors
    def _is_tty():
        return sys.stdout.isatty()

    def _green(s):
        return f"\033[32m{s}\033[0m" if _is_tty() else s

    def _yellow(s):
        return f"\033[33m{s}\033[0m" if _is_tty() else s

    def _red(s):
        return f"\033[31m{s}\033[0m" if _is_tty() else s

    def _dim(s):
        return f"\033[2m{s}\033[0m" if _is_tty() else s

    print(_dim("keep-focused update"))
    print(f"  Current version: {_green(__version__)}")
    remote_version = _fetch_remote_version()
    if remote_version:
        print(f"  Latest version:  {_green(remote_version)}")
        if remote_version == __version__ and not force:
            print(_green("✓ Already up to date."))
            if not check_only:
                print(_dim("  Use --force to reinstall anyway."))
            return 0
        elif remote_version != __version__:
            print(_yellow(f"  → Update available: {__version__} → {remote_version}"))
    else:
        print(_yellow("  ! Could not fetch remote version (offline?), proceeding with update..."))
        if check_only:
            print("  (check only – not updating)")
            return 0

    if check_only:
        print("  (check only – not updating)")
        return 0

    # Try git first if we are in a repo checkout
    repo_root = _find_repo_root()
    install_dir = _current_install_dir()
    print(f"  Install dir: {_dim(str(install_dir))}")
    if repo_root:
        print(f"  Repo detected: {_dim(str(repo_root))}")
        if _update_via_git(repo_root):
            print(_green("✓ Updated via git pull."))
            # After git pull, need to reinstall to install_dir if different
            # If repo_root != install_dir, also sync
            if repo_root.resolve() != install_dir.resolve():
                print(f"  → Syncing to {install_dir}...")
                # Re-run install.sh from repo_root
                local_install = repo_root / "install.sh"
                if local_install.exists():
                    result = subprocess.run(["bash", str(local_install)])
                    if result.returncode == 0:
                        print(_green("✓ Synced to install dir."))
                        return 0
                    else:
                        print(_red("✗ Sync failed, but git pull succeeded."))
                        return 1
                else:
                    # Manual sync via rsync/cp
                    try:
                        if shutil.which("rsync"):
                            subprocess.run(
                                [
                                    "rsync",
                                    "-a",
                                    "--delete",
                                    "--exclude",
                                    ".git",
                                    "--exclude",
                                    "__pycache__",
                                    str(repo_root / "keep_focused"),
                                    str(install_dir) + "/",
                                ],
                                check=False,
                            )
                        else:
                            shutil.rmtree(install_dir / "keep_focused", ignore_errors=True)
                            shutil.copytree(repo_root / "keep_focused", install_dir / "keep_focused", dirs_exist_ok=True)
                        print(_green("✓ Synced to install dir."))
                        return 0
                    except Exception as e:
                        print(_red(f"✗ Sync failed: {e}"))
                        return 1
            return 0
        else:
            print(_yellow("  git pull failed or not a git repo, trying install.sh..."))

    # Fallback: install.sh via curl
    print("  → Updating via install.sh (no git, no sudo, no pip)...")
    if _update_via_install_sh():
        print(_green("✓ Updated successfully."))
        print(f"  Run {_green('keep-focused')} to launch, or {_dim('keep-focused update --check')} to verify.")
        return 0
    else:
        print(_red("✗ Update failed."))
        print(_dim("  Try manually: curl -fsSL https://raw.githubusercontent.com/xweinp/keep-focused/main/install.sh | bash"))
        return 1
