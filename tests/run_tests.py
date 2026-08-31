#!/usr/bin/env python3
"""Fallback test runner when pytest is not available – uses only stdlib."""

import os
import sys
import tempfile
import pathlib
import traceback
import importlib.util
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Provide mock pytest if not available
try:
    import pytest  # noqa: F401
except ModuleNotFoundError:
    import types

    mock_pytest = types.ModuleType("pytest")

    @contextmanager
    def raises(exc, match=None):
        try:
            yield
            raise AssertionError(f"Expected {exc} but no exception raised")
        except exc as e:
            if match:
                import re

                if not re.search(match, str(e)):
                    raise AssertionError(f"Expected match '{match}' in '{e}'")

    def fixture(*args, **kwargs):
        def decorator(func):
            return func

        if args and callable(args[0]) and not kwargs:
            return args[0]
        return decorator

    mock_pytest.raises = raises
    mock_pytest.fixture = fixture
    mock_pytest.mark = types.SimpleNamespace(parametrize=lambda *a, **kw: lambda f: f)
    sys.modules["pytest"] = mock_pytest

# Mock pytest fixtures minimally
class TmpEnv:
    def __init__(self, tmp_path, monkeypatch_dict=None, arrow=False):
        self.tmp_path = tmp_path
        self.hosts = tmp_path / "hosts"
        self.config = tmp_path / "config.json"
        self.service = tmp_path / "service"
        self.tmp = tmp_path
        self.hosts.write_text("127.0.0.1 localhost\n::1 localhost\n")
        self.env = {
            "KEEP_FOCUSED_HOSTS": str(self.hosts),
            "KEEP_FOCUSED_CONFIG": str(self.config),
            "KEEP_FOCUSED_SERVICE": str(self.service),
            "XDG_CONFIG_HOME": str(tmp_path / ".config"),
            "HOME": str(tmp_path),
        }
        if arrow:
            self.env["KEEP_FOCUSED_ARROW"] = "1"
            self.env.pop("KEEP_FOCUSED_NO_ARROW", None)
        else:
            self.env["KEEP_FOCUSED_NO_ARROW"] = "1"
            self.env.pop("KEEP_FOCUSED_ARROW", None)

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def apply(self):
        for k, v in self.env.items():
            os.environ[k] = v
        # Ensure opposite arrow var is cleared
        if "KEEP_FOCUSED_ARROW" in self.env:
            os.environ.pop("KEEP_FOCUSED_NO_ARROW", None)
        else:
            os.environ.pop("KEEP_FOCUSED_ARROW", None)

    def cleanup(self):
        for k in list(self.env.keys()) + ["KEEP_FOCUSED_ARROW", "KEEP_FOCUSED_NO_ARROW", "XDG_CONFIG_HOME", "HOME"]:
            os.environ.pop(k, None)


def run_one(test_func, tmp_path):
    # Setup tmp_env like pytest fixture – handle both tmp_env and tmp_env_arrow
    import inspect

    sig = inspect.signature(test_func)
    # Determine if test needs arrow env
    needs_arrow = "tmp_env_arrow" in sig.parameters
    env = TmpEnv(tmp_path, arrow=needs_arrow)
    # For arrow tests, also need to mock isatty to True (like conftest does)
    isatty_patches = []
    if needs_arrow:
        # Mock sys.stdin/stdout.isatty to True for arrow navigation
        isatty_patches.append(patch.object(sys.stdin, "isatty", return_value=True))
        isatty_patches.append(patch.object(sys.stdout, "isatty", return_value=True))
        for p in isatty_patches:
            p.start()
    old_env = {k: os.environ.get(k) for k in env.env}
    # Also save ARROW/NO_ARROW plus XDG/HOME
    old_arrow = os.environ.get("KEEP_FOCUSED_ARROW")
    old_no_arrow = os.environ.get("KEEP_FOCUSED_NO_ARROW")
    old_xdg = os.environ.get("XDG_CONFIG_HOME")
    old_home = os.environ.get("HOME")
    env.apply()
    try:
        # Call test func with fixtures
        kwargs = {}
        if "tmp_env" in sig.parameters:
            kwargs["tmp_env"] = env
        if "tmp_env_arrow" in sig.parameters:
            kwargs["tmp_env_arrow"] = env
        if "tmp_path" in sig.parameters:
            kwargs["tmp_path"] = tmp_path
        if "monkeypatch" in sig.parameters:
            # Create a minimal monkeypatch object
            class MP:
                def setenv(self, k, v):
                    os.environ[k] = str(v)

                def delenv(self, k, raising=True):
                    if raising and k not in os.environ:
                        raise KeyError(k)
                    os.environ.pop(k, None)

                def setattr(self, target, name=None, value=None, raising=True):
                    # Handle monkeypatch.setattr("a.b.c", value) 2-arg form
                    if isinstance(target, str) and "." in target and value is None and name is not None and not isinstance(name, str):
                        # Actually called as setattr("keep_focused.update.perform_update", lambda)
                        # Here target is string path, name is value
                        value = name
                        parts = target.rsplit(".", 1)
                        mod_name, attr = parts
                        import importlib

                        mod = importlib.import_module(mod_name)
                        setattr(mod, attr, value)
                        return
                    if isinstance(target, str) and "." in target and isinstance(name, str) and value is None:
                        # Called as setattr("sys.stdin.isatty", True) – not used
                        pass
                    import importlib

                    if isinstance(target, str):
                        # Try to handle sys.stdin.isatty etc.
                        if target in ("sys.stdin.isatty", "sys.stdout.isatty"):
                            obj = sys.stdin if "stdin" in target else sys.stdout
                            patcher = patch.object(obj, "isatty", return_value=name if value is None else value)
                            patcher.start()
                            if not hasattr(MP, "_patchers"):
                                MP._patchers = []
                            MP._patchers.append(patcher)
                            return
                        # Generic string target with 3 args: setattr("mod.attr", "attr", value) not used
                        parts = target.rsplit(".", 1)
                        mod_name, attr = parts
                        mod = importlib.import_module(mod_name) if "." in mod_name else __import__(mod_name)
                        setattr(mod, attr, name if value is None else value)
                        return
                    # Fallback: target is object, name is attr string
                    setattr(target, name, value)

                def undo(self):
                    if hasattr(self, "_patchers"):
                        for p in self._patchers:
                            p.stop()

            mp = MP()
            kwargs["monkeypatch"] = mp
            try:
                result = test_func(**kwargs)
            finally:
                mp.undo()
        else:
            result = test_func(**kwargs)
        return True, None
    except BaseException as e:
        if isinstance(e, SystemExit):
            tb = traceback.format_exc()
            return False, f"Unexpected SystemExit({e.code}):\n{tb}"
        tb = traceback.format_exc()
        return False, tb
    finally:
        # Stop isatty patches
        for p in isatty_patches:
            try:
                p.stop()
            except Exception:
                pass
        # Restore env
        for k in env.env:
            if old_env[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_env[k]
        if old_arrow is None:
            os.environ.pop("KEEP_FOCUSED_ARROW", None)
        else:
            os.environ["KEEP_FOCUSED_ARROW"] = old_arrow
        if old_no_arrow is None:
            os.environ.pop("KEEP_FOCUSED_NO_ARROW", None)
        else:
            os.environ["KEEP_FOCUSED_NO_ARROW"] = old_no_arrow
        if old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = old_xdg
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


def main():
    test_dir = Path(__file__).parent
    test_files = sorted(test_dir.glob("test_*.py"))
    total = 0
    passed = 0
    failed = 0
    for f in test_files:
        if f.name == "run_tests.py":
            continue
        print(f"\n=== {f.name} ===")
        spec = importlib.util.spec_from_file_location(f"tests.{f.stem}", f)
        mod = importlib.util.module_from_spec(spec)
        # Need to handle conftest fixtures - we mocked them
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            print(f"  ! Failed to import {f.name}: {e}")
            traceback.print_exc()
            continue
        for name in dir(mod):
            if name.startswith("test_"):
                func = getattr(mod, name)
                if callable(func):
                    total += 1
                    # Create fresh tmp_path for each test
                    with tempfile.TemporaryDirectory() as td:
                        tmp_path = Path(td)
                        # Need to reload modules that use KEEP_FOCUSED_* at import time?
                        # Most modules read env at runtime, so fine
                        ok, tb = run_one(func, tmp_path)
                        if ok:
                            print(f"  ✓ {name}")
                            passed += 1
                        else:
                            print(f"  ✗ {name}")
                            print(tb)
                            failed += 1
    print(f"\n{'='*50}")
    print(f"Total: {total}, Passed: {passed}, Failed: {failed}")
    if failed:
        sys.exit(1)
    else:
        print("All tests passed!")


if __name__ == "__main__":
    main()
