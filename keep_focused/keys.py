"""Key reading helpers for arrow navigation – stdlib only, no deps."""

import os
import sys
import select

# ANSI for UI
REVERSE = "\033[7m"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"


def is_interactive() -> bool:
    """True if we can do arrow navigation (real TTY, not piped, not in tests)."""
    # Allow disabling via env for tests
    if os.environ.get("KEEP_FOCUSED_NO_ARROW"):
        return False
    # Check for mocked hosts/config/service (tests) – fallback to input() to allow mocking via builtins.input
    if os.environ.get("KEEP_FOCUSED_HOSTS") or os.environ.get("KEEP_FOCUSED_CONFIG"):
        # In tests we mock input/getpass, not arrow keys. Use input fallback unless explicitly allowed
        if not os.environ.get("KEEP_FOCUSED_ARROW"):
            return False
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _has_termios() -> bool:
    try:
        import termios  # noqa: F401
        import tty  # noqa: F401

        return True
    except ImportError:
        return False


def read_key() -> str:
    """Read a single key press. Returns: 'up','down','enter','space','esc','q', or single char."""
    if not _has_termios() or not is_interactive():
        # Fallback: use input() – caller should handle
        return ""

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        # Hide cursor while reading? Caller handles.
        ch = os.read(fd, 1).decode("utf-8", errors="ignore")
        if ch == "\x1b":  # ESC or arrow
            # Check if more chars available (arrow is ESC + [ + A/B)
            # Use select with short timeout to avoid blocking on lone Esc
            r, _, _ = select.select([sys.stdin], [], [], 0.15)
            if r:
                seq = os.read(fd, 2).decode("utf-8", errors="ignore")
                if seq == "[A":
                    return "up"
                if seq == "[B":
                    return "down"
                if seq == "[C":
                    return "right"
                if seq == "[D":
                    return "left"
                # Other ESC sequences
                return "esc"
            else:
                return "esc"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == " ":
            return "space"
        if ch == "\x03":  # Ctrl+C
            raise KeyboardInterrupt
        if ch == "\x7f":
            return "backspace"
        # Normalize to lower for a/n/c/q etc.
        if ch:
            return ch.lower()
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        # Ensure cursor shown is handled by caller


def read_key_with_fallback() -> str:
    """Same as read_key but never raises, returns '' on failure."""
    try:
        return read_key()
    except KeyboardInterrupt:
        raise
    except Exception:
        return ""
