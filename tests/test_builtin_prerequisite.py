"""Tests for BuiltinPrerequisite env var and package checking."""

import os
from unittest.mock import patch

from openpaw.builtins.base import BuiltinPrerequisite


def test_empty_prerequisites_satisfied():
    """Empty prerequisites are always satisfied."""
    prereq = BuiltinPrerequisite()
    assert prereq.is_satisfied() is True
    assert prereq.missing() == []


def test_env_var_satisfied():
    """Env var prerequisite satisfied when set."""
    with patch.dict(os.environ, {"TEST_API_KEY": "secret"}):
        prereq = BuiltinPrerequisite(env_vars=["TEST_API_KEY"])
        assert prereq.is_satisfied() is True
        assert prereq.missing() == []


def test_env_var_missing():
    """Env var prerequisite fails when not set."""
    with patch.dict(os.environ, {}, clear=True):
        prereq = BuiltinPrerequisite(env_vars=["NONEXISTENT_KEY"])
        assert prereq.is_satisfied() is False
        assert prereq.missing() == ["env:NONEXISTENT_KEY"]


def test_env_var_empty_string():
    """Empty string env var is treated as missing."""
    with patch.dict(os.environ, {"EMPTY_KEY": ""}):
        prereq = BuiltinPrerequisite(env_vars=["EMPTY_KEY"])
        assert prereq.is_satisfied() is False
        assert prereq.missing() == ["env:EMPTY_KEY"]


def test_package_satisfied():
    """Package prerequisite satisfied when installed."""
    prereq = BuiltinPrerequisite(packages=["json"])  # stdlib, always available
    assert prereq.is_satisfied() is True
    assert prereq.missing() == []


def test_package_missing():
    """Package prerequisite fails when not installed."""
    prereq = BuiltinPrerequisite(packages=["nonexistent_package_xyz"])
    assert prereq.is_satisfied() is False
    assert prereq.missing() == ["package:nonexistent_package_xyz"]


def test_both_satisfied():
    """Both env and package prerequisites satisfied."""
    with patch.dict(os.environ, {"TEST_KEY": "val"}):
        prereq = BuiltinPrerequisite(env_vars=["TEST_KEY"], packages=["json"])
        assert prereq.is_satisfied() is True
        assert prereq.missing() == []


def test_env_ok_package_missing():
    """Env satisfied but package missing fails overall."""
    with patch.dict(os.environ, {"TEST_KEY": "val"}):
        prereq = BuiltinPrerequisite(
            env_vars=["TEST_KEY"],
            packages=["nonexistent_package_xyz"],
        )
        assert prereq.is_satisfied() is False
        assert prereq.missing() == ["package:nonexistent_package_xyz"]


def test_env_missing_package_ok():
    """Env missing but package satisfied fails overall."""
    with patch.dict(os.environ, {}, clear=True):
        prereq = BuiltinPrerequisite(
            env_vars=["MISSING_KEY"],
            packages=["json"],
        )
        assert prereq.is_satisfied() is False
        assert prereq.missing() == ["env:MISSING_KEY"]


def test_multiple_env_vars_partial():
    """Multiple env vars with partial availability."""
    with patch.dict(os.environ, {"KEY_A": "val"}, clear=True):
        prereq = BuiltinPrerequisite(env_vars=["KEY_A", "KEY_B"])
        assert prereq.is_satisfied() is False
        assert prereq.missing() == ["env:KEY_B"]


def test_multiple_packages_partial():
    """Multiple packages with partial availability."""
    prereq = BuiltinPrerequisite(packages=["json", "nonexistent_pkg_abc"])
    assert prereq.is_satisfied() is False
    assert prereq.missing() == ["package:nonexistent_pkg_abc"]


def test_package_with_spec_error():
    """Packages that raise ValueError on find_spec are handled gracefully."""
    import importlib.util

    def mock_find_spec(name):
        if name == "broken_spec":
            raise ValueError("__spec__ is not set")
        return importlib.util.find_spec("json")  # Always return valid for other packages

    with patch("importlib.util.find_spec", side_effect=mock_find_spec):
        prereq = BuiltinPrerequisite(packages=["broken_spec"])
        assert prereq.is_satisfied() is False
        assert prereq.missing() == ["package:broken_spec"]
