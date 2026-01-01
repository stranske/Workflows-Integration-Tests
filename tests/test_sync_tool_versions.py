"""Tests for scripts/sync_tool_versions.py."""

import sys
from io import StringIO

import pytest


def test_main_success_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test check mode returns success."""
    monkeypatch.setattr(sys, "argv", ["sync_tool_versions.py", "--check"])

    from scripts.sync_tool_versions import main

    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)

    result = main()

    assert result == 0
    assert "✅" in captured_output.getvalue()
    assert "Tool versions are aligned" in captured_output.getvalue()


def test_main_success_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test apply mode returns success."""
    monkeypatch.setattr(sys, "argv", ["sync_tool_versions.py", "--apply"])

    from scripts.sync_tool_versions import main

    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)

    result = main()

    assert result == 0
    assert "✅" in captured_output.getvalue()


def test_main_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test script runs successfully with no arguments."""
    monkeypatch.setattr(sys, "argv", ["sync_tool_versions.py"])

    from scripts.sync_tool_versions import main

    result = main()
    assert result == 0


def test_main_both_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test script handles both --check and --apply flags."""
    monkeypatch.setattr(sys, "argv", ["sync_tool_versions.py", "--check", "--apply"])

    from scripts.sync_tool_versions import main

    result = main()
    assert result == 0


def test_main_via_command_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test running main via command line invocation."""
    import scripts.sync_tool_versions

    monkeypatch.setattr(sys, "argv", ["sync_tool_versions.py", "--check"])
    captured_output = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)

    result = scripts.sync_tool_versions.main()

    assert result == 0
    assert "✅" in captured_output.getvalue()
