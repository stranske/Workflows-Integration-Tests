"""Tests for tools/resolve_mypy_pin.py.

Note: The script reads python_version from pyproject.toml's [tool.mypy] section
and uses that as the default. Tests must account for this behavior.
"""

import sys
from io import StringIO
from pathlib import Path

import pytest


def test_main_with_github_output_and_pyproject(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test script prefers pyproject.toml python_version when present."""
    # Create a pyproject.toml with mypy config
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.mypy]\npython_version = "3.12"\n')

    output_file = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("MATRIX_PYTHON_VERSION", "3.13")  # Should be ignored
    monkeypatch.chdir(tmp_path)

    # Reimport to pick up new working directory
    import importlib

    import tools.resolve_mypy_pin

    importlib.reload(tools.resolve_mypy_pin)
    from tools.resolve_mypy_pin import main

    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)

    result = main()

    assert result == 0
    assert output_file.exists()
    content = output_file.read_text()
    # pyproject.toml takes precedence
    assert "python-version=3.12" in content


def test_main_falls_back_to_matrix_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test script uses MATRIX_PYTHON_VERSION when no pyproject.toml."""
    # No pyproject.toml in tmp_path
    output_file = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("MATRIX_PYTHON_VERSION", "3.13")
    monkeypatch.chdir(tmp_path)

    import importlib

    import tools.resolve_mypy_pin

    importlib.reload(tools.resolve_mypy_pin)
    from tools.resolve_mypy_pin import main

    result = main()

    assert result == 0
    content = output_file.read_text()
    assert "python-version=3.13" in content


def test_main_defaults_to_311(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test script uses 3.11 as default when nothing is set."""
    # No pyproject.toml
    monkeypatch.delenv("MATRIX_PYTHON_VERSION", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.chdir(tmp_path)

    import importlib

    import tools.resolve_mypy_pin

    importlib.reload(tools.resolve_mypy_pin)
    from tools.resolve_mypy_pin import main

    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)

    result = main()

    assert result == 0
    assert "python-version=3.11" in captured_output.getvalue()


def test_main_without_github_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test script works locally without GITHUB_OUTPUT."""
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("MATRIX_PYTHON_VERSION", "3.11")
    monkeypatch.chdir(tmp_path)  # No pyproject.toml

    import importlib

    import tools.resolve_mypy_pin

    importlib.reload(tools.resolve_mypy_pin)
    from tools.resolve_mypy_pin import main

    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)

    result = main()

    assert result == 0
    assert "python-version=3.11" in captured_output.getvalue()
