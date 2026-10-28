"""Workflow Python pins follow the fleet standard (3.14 first, 3.13 backup)."""

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))
RETIRED = re.compile(r"(?<![\d.])3\.12(?![\d])")
PIN_LINE = re.compile(r"python[-_]versions?|PYTHON_VERSION|^\s*(-\s*)?name:", re.IGNORECASE)


def _offenders(text: str) -> list[str]:
    return [
        f"{number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), start=1)
        if PIN_LINE.search(line) and RETIRED.search(line)
    ]


def test_scan_finds_workflows() -> None:
    assert WORKFLOWS, "no workflow files found; the pin scan would pass vacuously"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_workflow_python_pins_follow_standard(workflow: Path) -> None:
    assert _offenders(workflow.read_text()) == []


def test_scan_detects_a_retired_pin() -> None:
    assert _offenders('python-version: "3.12"\n') == ["1: python-version: \"3.12\""]
    assert _offenders("name: Basic (3.12 only)\n")
    assert _offenders('python-versions: \'["3.13", "3.14"]\'\n') == []
