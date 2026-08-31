import pytest

from keep_focused.auth import MIN_PASSWORD_LENGTH, hash_password, verify_password


def test_password_min_length_enforced():
    short = "a" * (MIN_PASSWORD_LENGTH - 1)
    with pytest.raises(ValueError, match="at least"):
        hash_password(short)
    # Exactly 20 should pass
    salt, h = hash_password("a" * MIN_PASSWORD_LENGTH)
    assert salt and h


def test_hash_and_verify():
    pw = "x" * 20
    salt, h = hash_password(pw)
    assert verify_password(pw, salt, h)
    assert not verify_password("wrong" * 5, salt, h)
    assert not verify_password(pw + "x", salt, h)


def test_verify_uses_constant_time():
    pw = "correct-horse-battery-staple-123"
    assert len(pw) >= MIN_PASSWORD_LENGTH
    salt, h = hash_password(pw)
    # Wrong password with same length should fail
    assert not verify_password("correct-horse-battery-staple-124", salt, h)


def test_hash_different_salts():
    pw = "y" * 20
    s1, h1 = hash_password(pw)
    s2, h2 = hash_password(pw)
    assert s1 != s2
    assert h1 != h2
    assert verify_password(pw, s1, h1)
    assert verify_password(pw, s2, h2)


def test_saved_password_roundtrip_via_config(tmp_env):
    """Save password to config file, reload, correct verifies, wrong fails."""
    from keep_focused.config import default_config, load_config, save_config

    pw = "correct-horse-battery-staple-keep-focused-01"
    assert len(pw) >= MIN_PASSWORD_LENGTH
    salt, h = hash_password(pw)
    cfg = default_config(h, salt, ["facebook.com"])
    save_config(cfg)

    loaded = load_config()
    assert loaded is not None
    assert loaded["salt"] == salt
    assert loaded["password_hash"] == h
    # correct password must verify against persisted hash
    assert verify_password(pw, loaded["salt"], loaded["password_hash"])
    # wrong passwords must not verify
    assert not verify_password("wrong-password-123456789012", loaded["salt"], loaded["password_hash"])
    assert not verify_password(pw + "x", loaded["salt"], loaded["password_hash"])
    assert not verify_password("", loaded["salt"], loaded["password_hash"])
    assert not verify_password("a" * MIN_PASSWORD_LENGTH, loaded["salt"], loaded["password_hash"])


def test_saved_password_case_and_whitespace_sensitive(tmp_env):
    """Password verification is case/whitespace sensitive after persistence."""
    from keep_focused.config import default_config, load_config, save_config

    pw = "My-Super-Long-Password-With-CAPS-123"
    assert len(pw) >= MIN_PASSWORD_LENGTH
    salt, h = hash_password(pw)
    save_config(default_config(h, salt, []))
    loaded = load_config()

    assert verify_password(pw, loaded["salt"], loaded["password_hash"])
    # case changed → fail
    assert not verify_password(pw.lower(), loaded["salt"], loaded["password_hash"])
    assert not verify_password(pw.upper(), loaded["salt"], loaded["password_hash"])
    # trailing space → fail
    assert not verify_password(pw + " ", loaded["salt"], loaded["password_hash"])
    assert not verify_password(" " + pw, loaded["salt"], loaded["password_hash"])


def test_password_change_invalidates_old(tmp_env):
    """After changing password, old no longer works, new does."""
    from keep_focused.config import default_config, load_config, save_config

    old_pw = "old-password-correct-horse-12345"
    new_pw = "new-password-correct-horse-67890"
    assert len(old_pw) >= MIN_PASSWORD_LENGTH
    assert len(new_pw) >= MIN_PASSWORD_LENGTH

    salt_old, h_old = hash_password(old_pw)
    save_config(default_config(h_old, salt_old, ["x.com"]))
    loaded = load_config()
    assert verify_password(old_pw, loaded["salt"], loaded["password_hash"])

    # simulate passwd change: new hash
    salt_new, h_new = hash_password(new_pw)
    loaded["salt"] = salt_new
    loaded["password_hash"] = h_new
    save_config(loaded)

    reloaded = load_config()
    assert verify_password(new_pw, reloaded["salt"], reloaded["password_hash"])
    assert not verify_password(old_pw, reloaded["salt"], reloaded["password_hash"])


def test_persisted_hash_is_not_plaintext(tmp_env):
    """Config file must not contain plaintext password."""
    from keep_focused.config import default_config, load_config, save_config
    import json

    pw = "super-secret-phrase-keep-focused-99"
    salt, h = hash_password(pw)
    save_config(default_config(h, salt, []))
    raw = tmp_env["config"].read_text()
    data = json.loads(raw)
    assert pw not in raw
    assert data["password_hash"] == h
    assert data["salt"] == salt
    assert data["password_hash"] != pw
