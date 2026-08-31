"""Password handling – PBKDF2-HMAC-SHA256, 20+ char enforcement."""

import getpass
import hashlib
import secrets

MIN_PASSWORD_LENGTH = 20
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16


def validate_password_length(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters "
            f"(got {len(password)})."
        )


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    """Return (salt_hex, hash_hex) for password. Generates salt if not given."""
    validate_password_length(password)
    if salt_hex is None:
        salt = secrets.token_bytes(SALT_BYTES)
        salt_hex = salt.hex()
    else:
        salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt_hex, dk.hex()


def verify_password(password: str, salt_hex: str, expected_hash_hex: str) -> bool:
    """Constant-time verification. Returns False for wrong/short passwords, never raises."""
    try:
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return secrets.compare_digest(dk.hex(), expected_hash_hex)
    except Exception:
        return False


def prompt_new_password(confirm: bool = True) -> str:
    """Interactively prompt for a new password (20+ chars, twice)."""
    while True:
        p1 = getpass.getpass(f"Set a password (min {MIN_PASSWORD_LENGTH} chars): ")
        if len(p1) < MIN_PASSWORD_LENGTH:
            print(f"  ✗ Too short ({len(p1)} chars). Must be at least {MIN_PASSWORD_LENGTH}.")
            continue
        if confirm:
            p2 = getpass.getpass("Confirm password: ")
            if p1 != p2:
                print("  ✗ Passwords do not match. Try again.")
                continue
        return p1


def prompt_password(prompt: str = "Enter password: ") -> str:
    return getpass.getpass(prompt)
