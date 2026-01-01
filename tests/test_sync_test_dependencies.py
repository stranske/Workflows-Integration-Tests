"""Tests for scripts/sync_test_dependencies.py."""

import sys
from io import StringIO

import pytest


def test_main_success_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test verify mode returns success."""
    monkeypatch.setattr(sys, "argv", ["sync_test_dependencies.py", "--verify"])

    # Import after argv is set
    from scripts.sync_test_dependencies import main

    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)

    result = main()

    assert result == 0
    assert "✅" in captured_output.getvalue()
    assert "All test dependencies" in captured_output.getvalue()


def test_main_success_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test fix mode returns success."""
    monkeypatch.setattr(sys, "argv", ["sync_test_dependencies.py", "--fix"])

    from scripts.sync_test_dependencies import main

    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)

    result = main()

    assert result == 0
    assert "✅" in captured_output.getvalue()


def test_main_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test script runs successfully with no arguments."""
    monkeypatch.setattr(sys, "argv", ["sync_test_dependencies.py"])

    from scripts.sync_test_dependencies import main

    result = main()
    assert result == 0


def test_main_both_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test script handles both --fix and --verify flags."""
    monkeypatch.setattr(sys, "argv", ["sync_test_dependencies.py", "--fix", "--verify"])

    from scripts.sync_test_dependencies import main

    result = main()
    assert result == 0


def test_main_via_command_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test running main via command line invocation."""
    import scripts.sync_test_dependencies

    monkeypatch.setattr(sys, "argv", ["sync_test_dependencies.py", "--verify"])
    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)

    # Simulate running as __main__
    result = scripts.sync_test_dependencies.main()

    assert result == 0
    assert "✅" in captured_output.getvalue()
