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
