from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Response:
    response_metadata = {"run_id": "trace-smoke"}
    content = "ok"


class _Runnable:
    def __init__(self) -> None:
        self.payload = None
        self.config = None

    def invoke(self, payload, *, config=None):
        self.payload = payload
        self.config = config
        return _Response()


def test_shared_langsmith_helpers_import_from_consumer_copy() -> None:
    trace_utils = importlib.import_module("scripts.langchain.trace_utils")
    task_validator = importlib.import_module("scripts.langchain.task_validator")

    assert hasattr(trace_utils, "invoke_with_trace")
    assert hasattr(task_validator, "validate_tasks")


def test_langsmith_trace_config_is_emitted_when_secret_present(monkeypatch) -> None:
    from scripts.langchain.trace_utils import invoke_with_trace

    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    runnable = _Runnable()

    response, _trace = invoke_with_trace(
        runnable,
        {"input": "value"},
        operation="integration_trace_smoke",
        issue_number=25,
    )

    assert response.content == "ok"
    assert runnable.payload == {"input": "value"}
    assert runnable.config["metadata"]["operation"] == "integration_trace_smoke"
    assert runnable.config["metadata"]["issue_number"] == "25"
    assert "operation:integration_trace_smoke" in runnable.config["tags"]


def test_no_secret_task_validation_is_clean_noop(monkeypatch) -> None:
    from scripts.langchain.task_validator import validate_tasks

    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    result = validate_tasks(
        ["Add deterministic smoke coverage"],
        context="integration smoke",
        use_llm=False,
    )

    assert result.tasks == ["Add deterministic smoke coverage"]
    assert result.provider_used is None
    assert result.langsmith_trace_id is None
    assert result.langsmith_trace_url is None
