"""Tests for capability_check.py — particularly that string input is handled correctly."""

import pytest

from scripts.langchain.capability_check import check_capability, classify_capabilities


def test_classify_capabilities_with_list_input() -> None:
    """List input (normal programmatic use) works unchanged."""
    result = classify_capabilities(["Create a minimal change", "Validate pipeline"], "")
    assert result.actionable_tasks == ["Create a minimal change", "Validate pipeline"]
    assert result.recommendation == "PROCEED"


def test_classify_capabilities_with_bulleted_string_input() -> None:
    """String with bullet-point tasks is parsed correctly (workflow passes raw file text)."""
    tasks_text = "- Create a minimal change\n- Validate the intake automation pipeline\n"
    result = classify_capabilities(tasks_text, "Must work correctly")
    assert result.actionable_tasks == [
        "Create a minimal change",
        "Validate the intake automation pipeline",
    ]
    assert result.recommendation == "PROCEED"


def test_classify_capabilities_string_does_not_iterate_characters() -> None:
    """A raw task sentence must NOT produce one entry per character."""
    sentence = "Create a minimal change to validate the intake automation pipeline."
    result = classify_capabilities(sentence, "")
    # _parse_tasks_from_text only picks up bullet lines; a plain sentence yields
    # no tasks rather than ~60 individual characters.
    assert all(len(t) > 1 for t in result.actionable_tasks), (
        "Tasks should not be individual characters"
    )


def test_check_capability_alias_accepts_string() -> None:
    """check_capability (workflow alias) must accept a string without error."""
    tasks_text = "- Task one\n- Task two\n"
    result = check_capability(tasks_text, "")
    assert len(result.actionable_tasks) == 2


def test_classify_capabilities_empty_string() -> None:
    """Empty string input returns REVIEW_NEEDED (no tasks detected)."""
    result = classify_capabilities("", "")
    assert result.actionable_tasks == []
    assert result.recommendation == "REVIEW_NEEDED"
