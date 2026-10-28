"""Workflow Python pins follow the fleet standard (3.14 first, 3.13 backup).

The scan is structural rather than a bare substring match, and needs no YAML
dependency: comments are removed first, a pin key's value is read from the
same line or from the indented block that follows it (a matrix written as a
list), and job/step ``name:`` values are checked too.
"""

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))
RETIRED = re.compile(r"(?<![\d.])3\.12(?!\d)")
PIN_KEY = re.compile(r"^\s*(?:-\s*)?(python[-_]versions?|PYTHON_VERSION|name)\s*:\s*(.*)$", re.I)


def _strip_comment(line: str) -> str:
    quote = None
    for index, char in enumerate(line):
        if quote:
            quote = None if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


def _offenders(text: str) -> list[str]:
    lines = [_strip_comment(line).rstrip() for line in text.splitlines()]
    found = []
    for number, line in enumerate(lines, start=1):
        match = PIN_KEY.match(line)
        if not match:
            continue
        key_indent = len(line) - len(line.lstrip())
        values = [match.group(2)]
        if not match.group(2).strip():
            for follow in lines[number:]:
                if follow.strip() and len(follow) - len(follow.lstrip()) <= key_indent:
                    break
                values.append(follow)
        if any(RETIRED.search(value) for value in values):
            found.append(f"{number}: {line.strip()}")
    return found


def test_scan_finds_workflows() -> None:
    assert WORKFLOWS, "no workflow files found; the pin scan would pass vacuously"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_workflow_python_pins_follow_standard(workflow: Path) -> None:
    assert _offenders(workflow.read_text()) == []


def test_scan_detects_a_retired_pin() -> None:
    assert _offenders('python-version: "3.12"\n') == ['1: python-version: "3.12"']
    assert _offenders("name: Basic (3.12 only)\n")
    assert _offenders("PYTHON_VERSION: '3.12'\n")


def test_scan_detects_a_block_list_matrix() -> None:
    text = "strategy:\n  python-version:\n    - \"3.13\"\n    - \"3.12\"\n  os: x\n"
    assert _offenders(text) == ["2: python-version:"]


def test_scan_ignores_comments_and_current_pins() -> None:
    assert _offenders('# python-version: "3.12"\n') == []
    assert _offenders('python-version: "3.14"  # was 3.12\n') == []
    assert _offenders("python-versions: '[\"3.13\", \"3.14\"]'\n") == []
    assert _offenders("python-version:\n  - \"3.14\"\nnext: 3.12\n") == []
