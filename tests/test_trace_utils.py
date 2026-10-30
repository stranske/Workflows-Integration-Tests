"""Behavioural tests for scripts/langchain/trace_utils.py."""

from __future__ import annotations

import inspect
import logging
from typing import Any

import pytest

from scripts.langchain import trace_utils
from scripts.langchain.trace_utils import (
    TraceInfo,
    build_trace_config,
    extract_trace_info,
    invoke_with_trace,
)


class _Response:
    content = "ok"


class _ConfigRunnable:
    """Runnable whose invoke() accepts ``config`` explicitly."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []

    def invoke(self, payload: Any, config: Any = None) -> _Response:
        self.calls.append((payload, config))
        return _Response()


class _NoConfigRunnable:
    """Runnable whose invoke() takes only the payload."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def invoke(self, payload: Any) -> _Response:
        self.calls.append(payload)
        return _Response()


class _VariadicWrapper:
    """Wrapper that forwards **kwargs to an inner runnable that rejects ``config``."""

    def __init__(self) -> None:
        self.inner: Any = _NoConfigRunnable()
        self.attempts: list[dict[str, Any]] = []

    def invoke(self, payload: Any, **kwargs: Any) -> Any:
        self.attempts.append(dict(kwargs))
        return self.inner.invoke(payload, **kwargs)


class _VariadicRaisesLookalike:
    """Raises a config-looking TypeError that was NOT produced by a forwarded call."""

    def invoke(self, payload: Any, **kwargs: Any) -> _Response:
        raise TypeError("got an unexpected keyword argument 'config'")


class _ExplodingRunnable:
    def invoke(self, payload: Any, config: Any = None) -> _Response:
        raise TypeError("boom: unrelated failure")


def _install_langsmith_helpers(
    monkeypatch: pytest.MonkeyPatch, *, trace_id: str | None, calls: list[dict[str, Any]]
) -> None:
    """Give tools.llm_provider the LangSmith helpers trace_utils prefers to import."""
    from tools import llm_provider

    def build_langsmith_metadata(**kwargs: Any) -> dict[str, object]:
        calls.append(kwargs)
        return {"metadata": {"from": "provider"}, "tags": ["provider-tag"]}

    monkeypatch.setattr(llm_provider, "build_langsmith_metadata", build_langsmith_metadata, False)
    monkeypatch.setattr(llm_provider, "extract_trace_id", lambda response: trace_id, False)
    monkeypatch.setattr(
        llm_provider,
        "derive_langsmith_trace_url",
        lambda tid: f"https://smith.example/trace/{tid}",
        False,
    )


@pytest.fixture
def no_provider_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every tools.llm_provider LangSmith helper fail, forcing trace_utils' fallbacks."""
    from tools import llm_provider

    def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("LangSmith helper unavailable")

    for name in ("build_langsmith_metadata", "extract_trace_id", "derive_langsmith_trace_url"):
        monkeypatch.setattr(llm_provider, name, unavailable, False)


def test_trace_info_available_and_as_dict() -> None:
    empty = TraceInfo()
    assert empty.available is False
    assert empty.as_dict() == {}

    id_only = TraceInfo(trace_id="abc")
    assert id_only.available is True
    assert id_only.as_dict() == {"langsmith_trace_id": "abc"}

    url_only = TraceInfo(trace_url="https://smith.example/t/1")
    assert url_only.available is True
    assert url_only.as_dict() == {"langsmith_trace_url": "https://smith.example/t/1"}

    both = TraceInfo(trace_id="abc", trace_url="https://smith.example/t/1")
    assert both.as_dict() == {
        "langsmith_trace_id": "abc",
        "langsmith_trace_url": "https://smith.example/t/1",
    }


def test_build_trace_config_falls_back_to_local_metadata(no_provider_helpers: None) -> None:
    config = build_trace_config(operation="triage", pr_number=7, issue_number=None)

    assert config["metadata"] == {"operation": "triage", "pr_number": "7", "issue_number": None}
    assert config["tags"] == ["operation:triage"]


def test_build_trace_config_prefers_provider_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    _install_langsmith_helpers(monkeypatch, trace_id=None, calls=calls)

    config = build_trace_config(operation="triage", pr_number=3, issue_number=4)

    assert config == {"metadata": {"from": "provider"}, "tags": ["provider-tag"]}
    assert calls == [{"operation": "triage", "pr_number": 3, "issue_number": 4}]


def test_extract_trace_info_without_provider_helpers_is_empty(no_provider_helpers: None) -> None:
    info = extract_trace_info(_Response())

    assert info == TraceInfo()
    assert info.available is False


def test_extract_trace_info_builds_url_from_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_langsmith_helpers(monkeypatch, trace_id="run-42", calls=[])

    info = extract_trace_info(_Response())

    assert info.trace_id == "run-42"
    assert info.trace_url == "https://smith.example/trace/run-42"


def test_extract_trace_info_without_trace_id_has_no_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_langsmith_helpers(monkeypatch, trace_id=None, calls=[])

    info = extract_trace_info(_Response())

    assert info.trace_id is None
    assert info.trace_url is None


def test_invoke_config_support_classifies_signatures() -> None:
    def explicit(payload: Any, config: Any = None) -> None: ...

    def variadic(payload: Any, **kwargs: Any) -> None: ...

    def plain(payload: Any) -> None: ...

    assert trace_utils._invoke_config_support(explicit) == "explicit"
    assert trace_utils._invoke_config_support(variadic) == "variadic"
    assert trace_utils._invoke_config_support(plain) == "none"


def test_invoke_config_support_unknown_when_signature_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_signature(_obj: Any) -> inspect.Signature:
        raise ValueError("no signature")

    monkeypatch.setattr(trace_utils.inspect, "signature", broken_signature)

    assert trace_utils._invoke_config_support(lambda payload: payload) == "unknown"


def test_invoke_with_trace_passes_config_when_supported(no_provider_helpers: None) -> None:
    runnable = _ConfigRunnable()

    response, trace = invoke_with_trace(
        runnable, {"q": 1}, operation="op", pr_number=9, issue_number=10
    )

    assert response.content == "ok"
    assert trace == TraceInfo()
    ((payload, config),) = runnable.calls
    assert payload == {"q": 1}
    assert config["metadata"] == {"operation": "op", "pr_number": "9", "issue_number": "10"}
    assert config["tags"] == ["operation:op"]


def test_invoke_with_trace_omits_config_when_invoke_takes_only_payload() -> None:
    runnable = _NoConfigRunnable()

    response, _trace = invoke_with_trace(runnable, "payload", operation="op")

    assert response.content == "ok"
    assert runnable.calls == ["payload"]


def test_invoke_with_trace_retries_without_config_on_direct_call_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the signature can't be inspected, a rejected ``config=`` is retried once without."""

    def broken_signature(_obj: Any) -> inspect.Signature:
        raise TypeError("no signature")

    monkeypatch.setattr(trace_utils.inspect, "signature", broken_signature)
    original = trace_utils._is_unsupported_config_error
    rejections: list[bool] = []

    def spy(exc: TypeError, *, allow_delegated: bool = False) -> bool:
        verdict = original(exc, allow_delegated=allow_delegated)
        rejections.append(verdict)
        return verdict

    monkeypatch.setattr(trace_utils, "_is_unsupported_config_error", spy)
    runnable = _NoConfigRunnable()

    response, _trace = invoke_with_trace(runnable, "payload", operation="op")

    assert response.content == "ok"
    # The config= attempt was made and rejected before the payload-only retry succeeded.
    assert rejections == [True]
    assert runnable.calls == ["payload"]


def test_invoke_with_trace_retries_delegated_variadic_wrapper() -> None:
    wrapper = _VariadicWrapper()

    response, _trace = invoke_with_trace(wrapper, "payload", operation="op")

    assert response.content == "ok"
    # First attempt carried config=, the retry did not; only the retry reached the inner runnable.
    assert [sorted(attempt) for attempt in wrapper.attempts] == [["config"], []]
    assert wrapper.inner.calls == ["payload"]


def test_invoke_with_trace_reraises_lookalike_type_error_from_variadic_wrapper() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'config'"):
        invoke_with_trace(_VariadicRaisesLookalike(), "payload", operation="op")


def test_invoke_with_trace_reraises_unrelated_type_error() -> None:
    with pytest.raises(TypeError, match="boom: unrelated failure"):
        invoke_with_trace(_ExplodingRunnable(), "payload", operation="op")


def test_invoke_with_trace_logs_trace_url_and_returns_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _install_langsmith_helpers(monkeypatch, trace_id="run-7", calls=[])
    runnable = _ConfigRunnable()

    with caplog.at_level(logging.INFO, logger=trace_utils.LOGGER.name):
        _response, trace = invoke_with_trace(runnable, "payload", operation="op")

    assert trace.trace_id == "run-7"
    assert trace.trace_url == "https://smith.example/trace/run-7"
    assert "LangSmith trace: https://smith.example/trace/run-7" in caplog.text
    # The provider-built config, not the local fallback, reached the runnable.
    assert runnable.calls[0][1]["tags"] == ["provider-tag"]


def test_unsupported_config_error_requires_config_related_message() -> None:
    unrelated = TypeError("unsupported operand type(s) for +")
    assert trace_utils._is_unsupported_config_error(unrelated) is False
    assert trace_utils._is_unsupported_config_error(unrelated, allow_delegated=True) is False

    # Right wording, but raised nowhere near invoke_with_trace: not a config rejection.
    detached = TypeError("invoke() got an unexpected keyword argument 'config'")
    assert trace_utils._is_unsupported_config_error(detached) is False
    assert trace_utils._is_unsupported_config_error(detached, allow_delegated=True) is False
