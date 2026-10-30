"""Tests for script execution as __main__."""

import subprocess
import sys
from pathlib import Path


def test_sync_test_dependencies_as_script() -> None:
    """Test sync_test_dependencies.py can be run as a script."""
    result = subprocess.run(
        [sys.executable, "scripts/sync_test_dependencies.py", "--verify"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    assert result.returncode == 0
    assert "✅" in result.stdout


def test_sync_tool_versions_as_script() -> None:
    """Test sync_tool_versions.py can be run as a script."""
    result = subprocess.run(
        [sys.executable, "scripts/sync_tool_versions.py", "--check"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    assert result.returncode == 0
    assert "✅" in result.stdout


def test_resolve_mypy_pin_as_script() -> None:
    """Test resolve_mypy_pin.py can be run as a script."""
    result = subprocess.run(
        [sys.executable, "tools/resolve_mypy_pin.py"],
        capture_output=True,
        text=True,
        # pyproject.toml's [tool.mypy] python_version wins over the matrix value; the two
        # differ so the test fails if config stops taking precedence.
        env={"MATRIX_PYTHON_VERSION": "3.14"},
        cwd=Path(__file__).parent.parent,
    )

    assert result.returncode == 0
    assert "python-version=3.13" in result.stdout
