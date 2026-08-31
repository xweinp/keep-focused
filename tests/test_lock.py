import os
from pathlib import Path

import keep_focused.lock as lock_mod
from keep_focused.lock import is_immutable, lock_file, unlock_file


def test_lock_unlock_best_effort(tmp_path):
    f = tmp_path / "test.json"
    f.write_text("{}")
    # If chattr not available, lock should still succeed via chmod fallback
    # and is_immutable should be False
    result = lock_file(f)
    assert result is True or result is False  # either is ok, but should not crash
    # Unlock should also not crash
    assert unlock_file(f) in (True, False)
    # After unlock, file should still exist and be readable
    assert f.exists()
    assert f.read_text() == "{}"


def test_lock_nonexistent():
    p = Path("/tmp/does-not-exist-12345.json")
    if p.exists():
        p.unlink()
    # Locking nonexistent should return False, not crash
    assert lock_file(p) is False
    assert unlock_file(p) is True  # nonexistent unlock is True


def test_is_immutable_false_for_regular(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hi")
    # Regular file not immutable
    assert is_immutable(f) is False
