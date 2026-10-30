"""Behavioural tests for scripts/langchain/task_validator.py."""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scripts.langchain import task_validator as tv
from scripts.langchain.task_validator import (
    TaskFate,
    TaskOutcome,
    TraceInfo,
    ValidationResult,
    merge_with_audit,
    refine_flagged_tasks,
    triage_tasks,
    validate_no_items_lost,
    validate_tasks,
)

GOOD_TASK = "Add unit tests for the parser module"


def _flagged(*tasks: str) -> list[dict[str, Any]]:
    return [{"task": t, "warnings": ["too_short"], "index": i} for i, t in enumerate(tasks)]


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("Make the output clean and nice", True),
        ("Ensure the module is properly documented", True),
        # A measurable word anywhere neutralises the subjective one.
        ("Ensure the tests pass", False),
        ("Write a parser", False),
    ],
)
def test_subjective_without_measurable(task: str, expected: bool) -> None:
    assert tv._has_subjective_without_measurable(task) is expected


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("Train staff on the new process", True),
        ("Schedule meeting with the platform team", True),
        ("Gather feedback from users", True),
        ("Request a PEER REVIEW of the change", True),
        ("Refactor the parser into two functions", False),
    ],
)
def test_looks_like_human_activity(task: str, expected: bool) -> None:
    assert tv._looks_like_human_activity(task) is expected


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("Define scope for: login page", True),
        ("  IMPLEMENT FOCUSED SLICE FOR: login", True),
        ("Validate focused slice for: x", True),
        ("Define approach for: x", True),
        ("Define the login page", False),
    ],
)
def test_expansion_prefix(task: str, expected: bool) -> None:
    assert tv._has_expansion_prefix(task) is expected


@pytest.mark.parametrize(
    ("task", "expected"),
    [(" , ; . ", True), ("()", True), ("a.", True), ("abc", False), ("fix it", False)],
)
def test_punctuation_fragment(task: str, expected: bool) -> None:
    assert tv._is_punctuation_fragment(task) is expected


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("# Heading", True),
        ("   ### Sub heading", True),
        ("#hashtag", False),
        ("Not # header", False),
    ],
)
def test_header_syntax(task: str, expected: bool) -> None:
    assert tv._is_header_syntax(task) is expected


def test_too_short_threshold_is_four_words() -> None:
    assert tv._is_too_short("one two three") is True
    assert tv._is_too_short("one two three four") is False


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


def test_triage_separates_clean_and_flagged_and_keeps_indexes() -> None:
    tasks = [GOOD_TASK, "", "# Phase one", "   ", "Train staff on rollout procedures today"]

    result = triage_tasks(tasks)

    assert result["clean"] == [GOOD_TASK]
    assert result["clean_items"] == [{"task": GOOD_TASK, "index": 0}]
    assert [(f["index"], f["warnings"]) for f in result["flagged"]] == [
        (2, ["too_short", "is_header"]),
        (4, ["human_activity"]),
    ]


def test_triage_reports_every_matching_signal() -> None:
    result = triage_tasks(["Define approach for:"])

    assert result["clean"] == []
    assert result["flagged"][0]["warnings"] == ["too_short", "recursive_prefix"]


def test_triage_of_nothing_is_empty() -> None:
    assert triage_tasks([]) == {"clean": [], "flagged": [], "clean_items": []}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


def test_task_fate_to_dict_includes_index_only_when_set() -> None:
    fate = TaskFate("orig", TaskOutcome.IMPROVED, "better", "why", ["w"])
    assert fate.to_dict() == {
        "original": "orig",
        "outcome": "improved",
        "result": "better",
        "reason": "why",
        "warnings": ["w"],
    }

    indexed = TaskFate("orig", TaskOutcome.DROPPED, None, "gone", original_index=3)
    assert indexed.to_dict()["original_index"] == 3
    assert indexed.to_dict()["result"] is None


def test_validation_result_to_dict_includes_trace_fields_only_when_set() -> None:
    bare = ValidationResult(tasks=["a"], fates=[], audit_summary="s")
    assert bare.to_dict() == {
        "tasks": ["a"],
        "fates": [],
        "audit_summary": "s",
        "provider_used": None,
    }

    traced = ValidationResult(
        tasks=["a"],
        fates=[TaskFate("a", TaskOutcome.KEPT, "a")],
        audit_summary="s",
        provider_used="openai",
        langsmith_trace_id="t1",
        langsmith_trace_url="https://smith.example/t1",
    )
    payload = traced.to_dict()
    assert payload["langsmith_trace_id"] == "t1"
    assert payload["langsmith_trace_url"] == "https://smith.example/t1"
    assert payload["fates"][0]["outcome"] == "kept"


# ---------------------------------------------------------------------------
# LLM client / prompt helpers
# ---------------------------------------------------------------------------


def _install_client_module(
    monkeypatch: pytest.MonkeyPatch, build: Callable[..., Any]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def build_chat_client(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return build(**kwargs)

    module = types.ModuleType("tools.langchain_client")
    module.build_chat_client = build_chat_client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tools.langchain_client", module)
    return calls


def test_get_llm_client_returns_none_when_client_module_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "tools.langchain_client", None)

    assert tv._get_llm_client() is None


def test_get_llm_client_returns_none_when_nothing_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client_module(monkeypatch, lambda **_kw: None)

    assert tv._get_llm_client() is None


def test_get_llm_client_returns_client_and_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    calls = _install_client_module(
        monkeypatch, lambda **_kw: types.SimpleNamespace(client=sentinel, provider="github-models")
    )

    assert tv._get_llm_client() == (sentinel, "github-models")
    assert tv._get_llm_client(force_openai=True) == (sentinel, "github-models")
    assert calls == [{"provider": None}, {"provider": "openai"}]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Error code: 401 - GitHub Models rejected the token", True),
        ("401 Unauthorized from models endpoint", True),
        ("401 Unauthorized", False),
        ("500 models outage", False),
    ],
)
def test_is_github_models_auth_error(message: str, expected: bool) -> None:
    assert tv._is_github_models_auth_error(RuntimeError(message)) is expected


def test_load_refinement_prompt_uses_default_when_file_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tv, "PROMPT_PATH", tmp_path / "missing.md")

    assert tv._load_refinement_prompt() == tv.REFINEMENT_PROMPT
    assert "{flagged_items}" in tv.REFINEMENT_PROMPT
    assert "{context}" in tv.REFINEMENT_PROMPT


def test_load_refinement_prompt_reads_and_strips_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prompt_file = tmp_path / "refine.md"
    prompt_file.write_text("\n  custom {flagged_items}\n\n", encoding="utf-8")
    monkeypatch.setattr(tv, "PROMPT_PATH", prompt_file)

    assert tv._load_refinement_prompt() == "custom {flagged_items}"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_refinement_response_maps_each_action() -> None:
    flagged = [
        {"task": "task a", "warnings": ["w1"], "index": 4},
        {"task": "task b", "warnings": [], "index": 7},
        {"task": "task c", "index": 9},
    ]
    response = """
    Here is my analysis:
    - KEEP: task a
    * improve: Rewrite task b with a verifiable outcome
    DROP: not a coding task
    """

    fates = tv._parse_refinement_response(response, flagged)

    assert [f.outcome for f in fates] == [
        TaskOutcome.KEPT,
        TaskOutcome.IMPROVED,
        TaskOutcome.DROPPED,
    ]
    kept, improved, dropped = fates
    assert kept.result == "task a"
    assert kept.warnings == ["w1"]
    assert kept.original_index == 4
    assert improved.result == "Rewrite task b with a verifiable outcome"
    assert improved.original == "task b"
    assert dropped.result is None
    assert dropped.reason == "not a coding task"
    assert dropped.warnings == []
    assert dropped.original_index == 9


def test_parse_refinement_response_keeps_original_when_llm_stops_early() -> None:
    flagged = _flagged("first task here", "second task here")

    fates = tv._parse_refinement_response("- IMPROVE: sharper first task", flagged)

    assert [f.outcome for f in fates] == [TaskOutcome.IMPROVED, TaskOutcome.UNPROCESSED]
    assert fates[1].result == "second task here"
    assert fates[1].reason == "LLM did not respond; keeping original"


def test_parse_refinement_response_with_no_matching_lines_is_all_unprocessed() -> None:
    fates = tv._parse_refinement_response("I could not decide.\n\n", _flagged("a b c d"))

    assert [f.outcome for f in fates] == [TaskOutcome.UNPROCESSED]
    assert fates[0].result == "a b c d"


# ---------------------------------------------------------------------------
# refine_flagged_tasks
# ---------------------------------------------------------------------------


class _FakeTemplate:
    def __init__(self, text: str) -> None:
        self.text = text

    def __or__(self, client: Any) -> tuple[_FakeTemplate, Any]:
        return (self, client)


def _install_langchain_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = types.ModuleType("langchain_core.prompts")
    prompts.ChatPromptTemplate = types.SimpleNamespace(  # type: ignore[attr-defined]
        from_template=_FakeTemplate
    )
    monkeypatch.setitem(sys.modules, "langchain_core", types.ModuleType("langchain_core"))
    monkeypatch.setitem(sys.modules, "langchain_core.prompts", prompts)


def test_refine_flagged_tasks_with_nothing_flagged_makes_no_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("LLM must not be consulted")

    monkeypatch.setattr(tv, "_get_llm_client", explode)

    assert refine_flagged_tasks([]) == ([], [], None, TraceInfo())


def test_refine_flagged_tasks_without_llm_keeps_originals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tv, "_get_llm_client", lambda force_openai=False: None)

    tasks, fates, provider, trace = refine_flagged_tasks(_flagged("tiny", "also tiny"))

    assert tasks == ["tiny", "also tiny"]
    assert [f.outcome for f in fates] == [TaskOutcome.UNPROCESSED] * 2
    assert fates[0].reason == "No LLM available; keeping original"
    assert fates[1].original_index == 1
    assert provider is None
    assert trace == TraceInfo()


def test_refine_flagged_tasks_without_langchain_keeps_originals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tv, "_get_llm_client", lambda force_openai=False: (object(), "openai"))
    monkeypatch.setitem(sys.modules, "langchain_core.prompts", None)

    tasks, fates, provider, _trace = refine_flagged_tasks(_flagged("tiny"))

    assert tasks == ["tiny"]
    assert fates[0].reason == "LangChain unavailable; keeping original"
    assert provider is None


def test_refine_flagged_tasks_applies_llm_decisions(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_langchain_stub(monkeypatch)
    client = object()
    monkeypatch.setattr(tv, "_get_llm_client", lambda force_openai=False: (client, "openai"))
    seen: dict[str, Any] = {}

    def fake_invoke(chain: Any, payload: Any, *, operation: str) -> tuple[Any, TraceInfo]:
        seen.update(chain=chain, payload=payload, operation=operation)
        reply = types.SimpleNamespace(content="- IMPROVE: Add tests for parser\n- DROP: header")
        return reply, TraceInfo(trace_id="t-1", trace_url="https://smith.example/t-1")

    monkeypatch.setattr(tv, "invoke_with_trace", fake_invoke)
    flagged = [
        {"task": "tests", "warnings": ["too_short", "subjective_language"], "index": 0},
        {"task": "# Header", "warnings": [], "index": 1},
    ]

    tasks, fates, provider, trace = refine_flagged_tasks(flagged, context="issue 12")

    assert tasks == ["Add tests for parser"]
    assert [f.outcome for f in fates] == [TaskOutcome.IMPROVED, TaskOutcome.DROPPED]
    assert provider == "openai"
    assert trace.trace_id == "t-1"
    assert seen["operation"] == "task_validator"
    assert seen["chain"][1] is client
    assert seen["payload"]["context"] == "issue 12"
    assert seen["payload"]["flagged_items"] == (
        "1. tests (warnings: too_short, subjective_language)\n2. # Header"
    )


def test_refine_flagged_tasks_uses_none_marker_for_empty_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_langchain_stub(monkeypatch)
    monkeypatch.setattr(tv, "_get_llm_client", lambda force_openai=False: (object(), "openai"))
    payloads: list[Any] = []

    def fake_invoke(chain: Any, payload: Any, *, operation: str) -> tuple[Any, TraceInfo]:
        payloads.append(payload)
        return "KEEP: tiny", TraceInfo()

    monkeypatch.setattr(tv, "invoke_with_trace", fake_invoke)

    tasks, fates, _provider, _trace = refine_flagged_tasks(_flagged("tiny"))

    # A bare string response has no .content, so str(response) is parsed instead.
    assert payloads[0]["context"] == "None"
    assert fates[0].outcome is TaskOutcome.KEPT
    assert tasks == ["tiny"]


def test_refine_flagged_tasks_falls_back_to_openai_on_github_models_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_langchain_stub(monkeypatch)
    github_client, openai_client = object(), object()
    requested: list[bool] = []

    def get_client(force_openai: bool = False) -> tuple[object, str]:
        requested.append(force_openai)
        return (openai_client, "openai") if force_openai else (github_client, "github-models")

    monkeypatch.setattr(tv, "_get_llm_client", get_client)
    used_clients: list[Any] = []

    def fake_invoke(chain: Any, payload: Any, *, operation: str) -> tuple[Any, TraceInfo]:
        used_clients.append(chain[1])
        if chain[1] is github_client:
            raise RuntimeError("Error code: 401 - models token rejected")
        return types.SimpleNamespace(content="KEEP: tiny"), TraceInfo()

    monkeypatch.setattr(tv, "invoke_with_trace", fake_invoke)

    tasks, fates, provider, _trace = refine_flagged_tasks(_flagged("tiny"))

    assert requested == [False, True]
    assert used_clients == [github_client, openai_client]
    assert provider == "openai"
    assert fates[0].outcome is TaskOutcome.KEPT
    assert tasks == ["tiny"]


def test_refine_flagged_tasks_reraises_auth_error_when_no_openai_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_langchain_stub(monkeypatch)

    def get_client(force_openai: bool = False) -> tuple[object, str] | None:
        return None if force_openai else (object(), "github-models")

    monkeypatch.setattr(tv, "_get_llm_client", get_client)

    def fake_invoke(chain: Any, payload: Any, *, operation: str) -> tuple[Any, TraceInfo]:
        raise RuntimeError("401 models unauthorized")

    monkeypatch.setattr(tv, "invoke_with_trace", fake_invoke)

    with pytest.raises(RuntimeError, match="401 models unauthorized"):
        refine_flagged_tasks(_flagged("tiny"))


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        ("openai", "401 models unauthorized"),  # auth-shaped, but not the GitHub Models provider
        ("github-models", "503 service unavailable"),  # GitHub Models, but not an auth error
    ],
)
def test_refine_flagged_tasks_reraises_errors_that_do_not_trigger_fallback(
    monkeypatch: pytest.MonkeyPatch, provider: str, message: str
) -> None:
    _install_langchain_stub(monkeypatch)
    requested: list[bool] = []

    def get_client(force_openai: bool = False) -> tuple[object, str]:
        requested.append(force_openai)
        return object(), provider

    monkeypatch.setattr(tv, "_get_llm_client", get_client)

    def fake_invoke(chain: Any, payload: Any, *, operation: str) -> tuple[Any, TraceInfo]:
        raise RuntimeError(message)

    monkeypatch.setattr(tv, "invoke_with_trace", fake_invoke)

    with pytest.raises(RuntimeError, match=message):
        refine_flagged_tasks(_flagged("tiny"))
    assert requested == [False]


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------


def test_validate_no_items_lost_accepts_fully_accounted_and_rejects_loss() -> None:
    validate_no_items_lost(original_count=5, result_count=3, dropped_count=2)
    validate_no_items_lost(original_count=2, result_count=3, dropped_count=0)

    with pytest.raises(ValueError, match="2 items unaccounted for"):
        validate_no_items_lost(original_count=5, result_count=2, dropped_count=1)


def test_merge_with_audit_restores_original_order_by_index() -> None:
    clean_items = [{"task": "clean first", "index": 0}, {"task": "clean last", "index": 3}]
    fates = [
        TaskFate("a", TaskOutcome.IMPROVED, "a improved", original_index=1),
        TaskFate("b", TaskOutcome.DROPPED, None, "header", original_index=2),
    ]

    final, audit = merge_with_audit(
        ["clean first", "clean last"], ["a improved"], fates, 4, clean_items
    )

    assert final == ["clean first", "a improved", "clean last"]
    assert audit == (
        "Task validation: 4 input → 3 output. "
        "Clean: 2, Kept: 0, Improved: 1, Dropped: 1, Fallback: 0"
    )


def test_merge_with_audit_without_indexes_appends_refined_after_clean() -> None:
    fates = [
        TaskFate("a", TaskOutcome.KEPT, "a"),
        TaskFate("b", TaskOutcome.UNPROCESSED, "b"),
    ]

    final, audit = merge_with_audit(["c"], ["a", "b"], fates, 3)

    assert final == ["c", "a", "b"]
    assert "Kept: 1" in audit
    assert "Fallback: 1" in audit


def test_merge_with_audit_falls_back_when_some_fate_has_no_index() -> None:
    clean_items = [{"task": "c", "index": 0}]
    fates = [TaskFate("a", TaskOutcome.KEPT, "a", original_index=None)]

    final, _audit = merge_with_audit(["c"], ["a"], fates, 2, clean_items)

    assert final == ["c", "a"]


def test_merge_with_audit_rejects_count_mismatch() -> None:
    fates = [TaskFate("a", TaskOutcome.KEPT, "a")]

    with pytest.raises(ValueError, match="Audit mismatch: 5 input items"):
        merge_with_audit(["c"], ["a"], fates, 5)


# ---------------------------------------------------------------------------
# validate_tasks
# ---------------------------------------------------------------------------


def test_validate_tasks_with_only_blank_input() -> None:
    result = validate_tasks(["", "   "])

    assert result.tasks == []
    assert result.fates == []
    assert result.audit_summary == "No tasks to validate"
    assert result.provider_used is None


def test_validate_tasks_all_clean_skips_refinement(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("refinement must not run when nothing is flagged")

    monkeypatch.setattr(tv, "refine_flagged_tasks", explode)

    result = validate_tasks([GOOD_TASK, "Write integration tests for the CLI entry point"])

    assert result.tasks == [GOOD_TASK, "Write integration tests for the CLI entry point"]
    assert result.fates == []
    assert result.audit_summary.endswith("2 input → 2 output. All clean.")


def test_validate_tasks_without_llm_keeps_flagged_in_original_position() -> None:
    tasks = ["# Phase one", "", GOOD_TASK, "Train staff on rollout procedures today"]

    result = validate_tasks(tasks, use_llm=False)

    assert result.tasks == ["# Phase one", GOOD_TASK, "Train staff on rollout procedures today"]
    assert [f.outcome for f in result.fates] == [TaskOutcome.UNPROCESSED] * 2
    # Indexes refer to the caller's list (blank entries included), not the filtered one.
    assert [f.original_index for f in result.fates] == [0, 3]
    assert result.fates[0].reason == "LLM disabled; keeping original"
    assert result.provider_used is None
    assert "Clean: 1" in result.audit_summary
    assert "Fallback: 2" in result.audit_summary


def test_validate_tasks_applies_llm_refinement(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_refine(
        flagged: Any, context: str = ""
    ) -> tuple[list[str], list[TaskFate], str, TraceInfo]:
        assert context == "ctx"
        fates = [
            TaskFate(
                flagged[0]["task"],
                TaskOutcome.IMPROVED,
                "Add tests for the parser",
                original_index=flagged[0]["index"],
            ),
            TaskFate(
                flagged[1]["task"],
                TaskOutcome.DROPPED,
                None,
                "human activity",
                original_index=flagged[1]["index"],
            ),
        ]
        return (
            ["Add tests for the parser"],
            fates,
            "openai",
            TraceInfo(trace_id="t9", trace_url="https://smith.example/t9"),
        )

    monkeypatch.setattr(tv, "refine_flagged_tasks", fake_refine)

    result = validate_tasks(["tests", GOOD_TASK, "Schedule meeting with the whole team"], "ctx")

    assert result.tasks == ["Add tests for the parser", GOOD_TASK]
    assert result.provider_used == "openai"
    assert result.langsmith_trace_id == "t9"
    assert result.langsmith_trace_url == "https://smith.example/t9"
    assert result.audit_summary == (
        "Task validation: 3 input → 2 output. "
        "Clean: 1, Kept: 0, Improved: 1, Dropped: 1, Fallback: 0"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_main_prints_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["task_validator.py", "--tasks", GOOD_TASK, "--json", "--no-llm"]
    )

    tv.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["tasks"] == [GOOD_TASK]
    assert payload["fates"] == []
    assert payload["provider_used"] is None


def test_main_prints_human_readable_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["task_validator.py", "--tasks", GOOD_TASK, "# Heading", "--context", "c", "--no-llm"],
    )

    tv.main()

    out = capsys.readouterr().out
    assert "Audit: Task validation: 2 input → 2 output." in out
    assert f"  - {GOOD_TASK}" in out
    assert "  - # Heading" in out
    assert "[unprocessed] # Heading" in out
    assert "Reason: LLM disabled; keeping original" in out


def test_main_without_tasks_reports_nothing_to_validate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["task_validator.py", "--json"])

    tv.main()

    assert json.loads(capsys.readouterr().out)["audit_summary"] == "No tasks to validate"
