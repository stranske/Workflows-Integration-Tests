"""Tests for tools/resolve_mypy_pin.py."""
import os
import sys
import tempfile
from io import StringIO
from pathlib import Path

import pytest


def test_main_with_github_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test script writes to GITHUB_OUTPUT file."""
    output_file = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("MATRIX_PYTHON_VERSION", "3.12")
    
    from tools.resolve_mypy_pin import main
    
    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)
    
    result = main()
    
    assert result == 0
    assert output_file.exists()
    content = output_file.read_text()
    assert "python-version=3.12" in content
    assert "Resolved mypy Python version: 3.12" in captured_output.getvalue()


def test_main_without_github_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test script works locally without GITHUB_OUTPUT."""
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("MATRIX_PYTHON_VERSION", "3.11")
    
    from tools.resolve_mypy_pin import main
    
    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)
    
    result = main()
    
    assert result == 0
    assert "python-version=3.11" in captured_output.getvalue()


def test_main_defaults_to_311(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test script uses 3.11 as default when MATRIX_PYTHON_VERSION not set."""
    monkeypatch.delenv("MATRIX_PYTHON_VERSION", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    
    from tools.resolve_mypy_pin import main
    
    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)
    
    result = main()
    
    assert result == 0
    assert "python-version=3.11" in captured_output.getvalue()


def test_main_with_custom_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test script respects custom Python version."""
    output_file = tmp_path / "output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("MATRIX_PYTHON_VERSION", "3.13")
    
    from tools.resolve_mypy_pin import main
    
    result = main()
    
    assert result == 0
    content = output_file.read_text()
    assert "python-version=3.13" in content


def test_main_via_command_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test running main via command line invocation."""
    import tools.resolve_mypy_pin
    
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("MATRIX_PYTHON_VERSION", "3.12")
    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)
    
    result = tools.resolve_mypy_pin.main()
    
    assert result == 0
    assert "python-version=3.12" in captured_output.getvalue()
