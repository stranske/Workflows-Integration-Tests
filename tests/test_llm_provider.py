"""Behavioural tests for tools/llm_provider.py (no network, no LangChain required)."""

from __future__ import annotations

import json
import logging
import runpy
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tools import llm_provider as lp
from tools.llm_provider import (
    CompletionAnalysis,
    FallbackChainProvider,
    GitHubModelsProvider,
    LLMProvider,
    OpenAIProvider,
    RegexFallbackProvider,
    SessionQualityContext,
    check_providers,
    get_llm_provider,
)

LONG_REASONING = "The session shows concrete edits and passing test runs. " * 5
ENV_VARS = ("GITHUB_TOKEN", "OPENAI_API_KEY", "LANGSMITH_API_KEY")


def _unset_env(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Remove env vars for this test only (setenv first so teardown restores the original)."""
    for name in names:
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)


def _response_json(**overrides: Any) -> str:
    data: dict[str, Any] = {
        "completed": ["Write parser"],
        "in_progress": ["Add CLI"],
        "blocked": ["Deploy"],
        "confidence": 0.9,
        "reasoning": LONG_REASONING,
    }
    data.update(overrides)
    return json.dumps(data)


class _FakeClient:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> Any:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return types.SimpleNamespace(content=self.content)


def _install_chat_openai(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Stub langchain_openai.ChatOpenAI and record its constructor kwargs."""
    created: list[dict[str, Any]] = []

    class ChatOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

    module = types.ModuleType("langchain_openai")
    module.ChatOpenAI = ChatOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_openai", module)
    return created


def _quality(**overrides: Any) -> SessionQualityContext:
    values: dict[str, Any] = {
        "has_agent_messages": True,
        "has_work_evidence": False,
        "file_change_count": 0,
        "successful_command_count": 0,
        "estimated_effort_score": 0,
        "data_quality": "high",
        "analysis_text_length": 1000,
    }
    values.update(overrides)
    return SessionQualityContext(**values)


class _StubProvider(LLMProvider):
    def __init__(self, name: str, available: bool = True, error: Exception | None = None) -> None:
        self._name = name
        self._available = available
        self._error = error
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return self._available

    def analyze_completion(
        self, session_output: str, tasks: list[str], context: str | None = None
    ) -> CompletionAnalysis:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return CompletionAnalysis([], [], [], 1.0, "stub", self._name)


# ---------------------------------------------------------------------------
# LangSmith + error classification
# ---------------------------------------------------------------------------


def test_setup_langsmith_tracing_disabled_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _unset_env(monkeypatch, "LANGSMITH_API_KEY", "LANGCHAIN_TRACING_V2", "LANGCHAIN_PROJECT")

    assert lp._setup_langsmith_tracing() is False
    assert "LANGCHAIN_TRACING_V2" not in lp.os.environ


def test_setup_langsmith_tracing_sets_defaults_but_respects_existing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "key")
    _unset_env(monkeypatch, "LANGCHAIN_TRACING_V2")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "my-project")

    with caplog.at_level(logging.INFO, logger=lp.logger.name):
        assert lp._setup_langsmith_tracing() is True

    assert lp.os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert lp.os.environ["LANGCHAIN_PROJECT"] == "my-project"
    assert "LangSmith tracing enabled for project: my-project" in caplog.text


def test_setup_langsmith_tracing_default_project_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "key")
    _unset_env(monkeypatch, "LANGCHAIN_PROJECT", "LANGCHAIN_TRACING_V2")

    assert lp._setup_langsmith_tracing() is True
    assert lp.os.environ["LANGCHAIN_PROJECT"] == "workflows-agents"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Error code: 413 - tokens_limit_reached", True),
        ("status code 413: Request body too large", True),
        ("413 tokens_limit_reached", False),  # no 'error code'/'status code' marker
        ("Error code: 413 - something else", False),  # 413 without a token-limit message
        ("Error code: 500 - tokens_limit_reached", False),
    ],
)
def test_is_token_limit_error(message: str, expected: bool) -> None:
    assert lp._is_token_limit_error(RuntimeError(message)) is expected


# ---------------------------------------------------------------------------
# GitHubModelsProvider
# ---------------------------------------------------------------------------


def test_github_models_availability_follows_token(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GitHubModelsProvider()
    assert provider.name == "github-models"

    _unset_env(monkeypatch, "GITHUB_TOKEN")
    assert provider.is_available() is False
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert provider.is_available() is True


def test_github_models_client_is_none_without_langchain_openai(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(sys.modules, "langchain_openai", None)

    with caplog.at_level(logging.WARNING, logger=lp.logger.name):
        assert GitHubModelsProvider()._get_client() is None

    assert "langchain_openai not installed" in caplog.text


def test_github_models_client_targets_github_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    created = _install_chat_openai(monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")

    GitHubModelsProvider()._get_client()

    assert created == [
        {
            "model": lp.DEFAULT_MODEL,
            "base_url": lp.GITHUB_MODELS_BASE_URL,
            "api_key": "gh-secret",
            "temperature": 0.1,
        }
    ]


def test_github_models_analyze_requires_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langchain_openai", None)

    with pytest.raises(RuntimeError, match="LangChain OpenAI not available"):
        GitHubModelsProvider().analyze_completion("output", ["task"])


def test_github_models_analyze_parses_client_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(_response_json())
    provider = GitHubModelsProvider()
    monkeypatch.setattr(provider, "_get_client", lambda: client)

    result = provider.analyze_completion("did the work", ["Write parser", "Add CLI"])

    assert result.completed_tasks == ["Write parser"]
    assert result.in_progress_tasks == ["Add CLI"]
    assert result.blocked_tasks == ["Deploy"]
    assert result.confidence == 0.9
    assert result.provider_used == "github-models"
    assert "- [ ] Write parser" in client.prompts[0]
    assert "did the work" in client.prompts[0]


def test_github_models_analyze_applies_quality_context(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GitHubModelsProvider()
    monkeypatch.setattr(provider, "_get_client", lambda: _FakeClient(_response_json()))

    result = provider.analyze_completion(
        "output", ["Write parser"], quality_context=_quality(data_quality="low")
    )

    assert result.confidence == 0.6
    assert result.raw_confidence == 0.9
    assert result.confidence_adjusted is True
    assert result.quality_warnings == ["Confidence capped from 90% to 60% due to low data quality"]


def test_github_models_analyze_logs_and_reraises_api_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    provider = GitHubModelsProvider()
    monkeypatch.setattr(
        provider, "_get_client", lambda: _FakeClient(error=ConnectionError("network down"))
    )

    with caplog.at_level(logging.ERROR, logger=lp.logger.name):
        with pytest.raises(ConnectionError, match="network down"):
            provider.analyze_completion("output", ["task"])

    assert "GitHub Models API error: network down" in caplog.text


def test_build_analysis_prompt_lists_tasks_and_truncates_output() -> None:
    prompt = GitHubModelsProvider()._build_analysis_prompt("A" * 8000 + "TAIL", ["one", "two"])

    assert "- [ ] one\n- [ ] two" in prompt
    assert "A" * 8000 in prompt
    assert "TAIL" not in prompt
    assert '"confidence": 0.85' in prompt


# ---- BS detector ----------------------------------------------------------


def test_validate_confidence_without_context_clamps_and_reports_nothing() -> None:
    provider = GitHubModelsProvider()

    assert provider._validate_confidence(1.7, 1, 0, None, "r") == (1.0, [])
    assert provider._validate_confidence(-0.2, 1, 0, None, "r") == (0.0, [])
    assert provider._validate_confidence(0.55, 1, 0, None, "r") == (0.55, [])


def test_validate_confidence_clean_session_is_untouched() -> None:
    confidence, warnings = GitHubModelsProvider()._validate_confidence(
        0.95, 2, 0, _quality(), LONG_REASONING
    )

    assert (confidence, warnings) == (0.95, [])


def test_validate_confidence_rule1_high_confidence_with_no_tasks_despite_work() -> None:
    quality = _quality(has_work_evidence=True, file_change_count=4, successful_command_count=6)

    confidence, warnings = GitHubModelsProvider()._validate_confidence(0.9, 0, 0, quality, "r")

    assert confidence == 0.3
    assert warnings == [
        "High confidence (90%) but no tasks detected despite 4 file changes "
        "and 6 successful commands"
    ]


def test_validate_confidence_rule1_needs_high_confidence() -> None:
    quality = _quality(has_work_evidence=True)

    confidence, warnings = GitHubModelsProvider()._validate_confidence(0.7, 0, 0, quality, "r")

    assert (confidence, warnings) == (0.7, [])


def test_validate_confidence_rule2_short_analysis_text_caps_at_point_four() -> None:
    confidence, warnings = GitHubModelsProvider()._validate_confidence(
        0.9, 1, 0, _quality(analysis_text_length=50), "r"
    )

    assert confidence == 0.4
    assert warnings == [
        "Analysis text suspiciously short (50 chars) - possible data loss in pipeline"
    ]


def test_validate_confidence_rule3_high_effort_but_no_tasks() -> None:
    confidence, warnings = GitHubModelsProvider()._validate_confidence(
        0.5, 0, 0, _quality(estimated_effort_score=31), "r"
    )

    assert confidence == 0.4
    assert warnings == ["Effort score (31) suggests work was done but no tasks detected"]


def test_validate_confidence_rule4_claims_no_evidence_despite_work() -> None:
    confidence, warnings = GitHubModelsProvider()._validate_confidence(
        0.9, 1, 0, _quality(has_work_evidence=True), "There is No Evidence of progress"
    )

    assert confidence == 0.35
    assert warnings == ["LLM claims 'no evidence' but session has file changes/commands"]


@pytest.mark.parametrize(
    ("data_quality", "cap"),
    [("high", 1.0), ("medium", 0.8), ("low", 0.6), ("minimal", 0.4), ("weird", 0.5)],
)
def test_validate_confidence_rule5_quality_caps(data_quality: str, cap: float) -> None:
    confidence, warnings = GitHubModelsProvider()._validate_confidence(
        1.0, 1, 0, _quality(data_quality=data_quality), "r"
    )

    assert confidence == cap
    if cap < 1.0:
        assert warnings == [
            f"Confidence capped from 100% to {cap:.0%} due to {data_quality} data quality"
        ]
    else:
        assert warnings == []


def test_validate_confidence_rules_stack_to_the_lowest_cap() -> None:
    quality = _quality(
        has_work_evidence=True,
        analysis_text_length=10,
        estimated_effort_score=50,
        data_quality="minimal",
    )

    confidence, warnings = GitHubModelsProvider()._validate_confidence(
        0.95, 0, 0, quality, "no work happened"
    )

    assert confidence == 0.3
    assert len(warnings) == 4  # rules 1-4 fire; the 0.4 quality cap no longer binds


# ---- response parsing -----------------------------------------------------


def test_parse_response_extracts_json_embedded_in_prose() -> None:
    content = f"Sure! Here you go:\n{_response_json(confidence=0.8)}\nHope that helps."

    result = GitHubModelsProvider()._parse_response(content, ["t"])

    assert result.completed_tasks == ["Write parser"]
    assert result.confidence == 0.8
    assert result.raw_confidence is None
    assert result.confidence_adjusted is False
    assert result.quality_warnings is None


def test_parse_response_defaults_for_missing_fields() -> None:
    result = GitHubModelsProvider()._parse_response("{}", ["t"])

    assert result.completed_tasks == []
    assert result.in_progress_tasks == []
    assert result.blocked_tasks == []
    assert result.confidence == 0.5
    assert result.reasoning == ""


def test_parse_response_without_json_returns_zero_confidence_analysis() -> None:
    result = GitHubModelsProvider()._parse_response("no braces here", ["t"])

    assert result.completed_tasks == []
    assert result.confidence == 0.0
    assert result.reasoning == "Failed to parse response: No JSON found in response"
    assert result.provider_used == "github-models"


def test_parse_response_with_malformed_json_returns_zero_confidence_analysis() -> None:
    result = GitHubModelsProvider()._parse_response('{"completed": [oops]}', ["t"])

    assert result.confidence == 0.0
    assert result.reasoning.startswith("Failed to parse response:")


def test_parse_response_with_non_numeric_confidence_is_handled() -> None:
    result = GitHubModelsProvider()._parse_response('{"confidence": "high"}', ["t"])

    assert result.confidence == 0.0
    assert result.reasoning.startswith("Failed to parse response:")


# ---------------------------------------------------------------------------
# OpenAIProvider
# ---------------------------------------------------------------------------


def test_openai_availability_follows_key(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAIProvider()
    assert provider.name == "openai"

    _unset_env(monkeypatch, "OPENAI_API_KEY")
    assert provider.is_available() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert provider.is_available() is True


def test_openai_client_uses_openai_key_and_default_base(monkeypatch: pytest.MonkeyPatch) -> None:
    created = _install_chat_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    OpenAIProvider()._get_client()

    assert created == [{"model": lp.DEFAULT_MODEL, "api_key": "sk-test", "temperature": 0.1}]


def test_openai_client_is_none_without_langchain_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langchain_openai", None)

    assert OpenAIProvider()._get_client() is None


def test_openai_analyze_requires_client(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAIProvider()
    monkeypatch.setattr(provider, "_get_client", lambda: None)

    with pytest.raises(RuntimeError, match="LangChain OpenAI not available"):
        provider.analyze_completion("output", ["task"])


def test_openai_analyze_reports_openai_as_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(_response_json())
    provider = OpenAIProvider()
    monkeypatch.setattr(provider, "_get_client", lambda: client)

    result = provider.analyze_completion("output", ["Write parser"])

    assert result.provider_used == "openai"
    assert result.completed_tasks == ["Write parser"]
    assert result.confidence == 0.9
    assert "- [ ] Write parser" in client.prompts[0]


def test_openai_analyze_logs_and_reraises_api_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    provider = OpenAIProvider()
    monkeypatch.setattr(provider, "_get_client", lambda: _FakeClient(error=ValueError("bad key")))

    with caplog.at_level(logging.ERROR, logger=lp.logger.name):
        with pytest.raises(ValueError, match="bad key"):
            provider.analyze_completion("output", ["task"])

    assert "OpenAI API error: bad key" in caplog.text


# ---------------------------------------------------------------------------
# RegexFallbackProvider
# ---------------------------------------------------------------------------


def test_regex_provider_is_always_available() -> None:
    provider = RegexFallbackProvider()
    assert provider.name == "regex-fallback"
    assert provider.is_available() is True


def test_regex_provider_marks_task_completed_when_words_and_completion_signal_match() -> None:
    tasks = ["Implement parser module", "Document release process"]

    result = RegexFallbackProvider().analyze_completion("Finished the parser work.", tasks)

    assert result.completed_tasks == ["Implement parser module"]
    assert result.blocked_tasks == []
    assert result.in_progress_tasks == []
    assert result.confidence == 0.3
    assert result.provider_used == "regex-fallback"
    assert result.reasoning == "Pattern-based analysis (no LLM available)"


def test_regex_provider_marks_task_blocked_on_blocker_signal() -> None:
    tasks = ["Deploy staging cluster", "Implement parser module"]

    result = RegexFallbackProvider().analyze_completion("The deploy is blocked by an error", tasks)

    assert result.blocked_tasks == ["Deploy staging cluster"]
    assert result.completed_tasks == []
    assert result.in_progress_tasks == []


def test_regex_provider_detects_in_progress_only_when_no_other_signal() -> None:
    output = "Working on the importer right now"

    result = RegexFallbackProvider().analyze_completion(output, ["Build importer pipeline"])

    assert result.in_progress_tasks == ["Build importer pipeline"]
    assert result.completed_tasks == []
    assert result.blocked_tasks == []


def test_regex_provider_ignores_short_words_and_unrelated_output() -> None:
    # "fix" and "it" are <=3 chars so they never count as a match, even with signals present.
    result = RegexFallbackProvider().analyze_completion("done: fix it", ["fix it"])

    assert result.completed_tasks == []
    assert result.in_progress_tasks == []
    assert result.blocked_tasks == []


def test_regex_provider_completion_wins_over_blocker_for_same_task() -> None:
    result = RegexFallbackProvider().analyze_completion(
        "finished the exporter but one test failed", ["Write exporter"]
    )

    assert result.completed_tasks == ["Write exporter"]
    assert result.blocked_tasks == []


# ---------------------------------------------------------------------------
# FallbackChainProvider
# ---------------------------------------------------------------------------


def test_chain_name_reflects_active_provider() -> None:
    chain = FallbackChainProvider([_StubProvider("a")])
    assert chain.name == "fallback-chain"

    chain.analyze_completion("out", ["t"])

    assert chain.name == "fallback-chain(a)"


def test_chain_availability_is_any_provider() -> None:
    assert FallbackChainProvider([_StubProvider("a", False), _StubProvider("b")]).is_available()
    assert not FallbackChainProvider([_StubProvider("a", False)]).is_available()
    assert not FallbackChainProvider([]).is_available()


def test_chain_skips_unavailable_and_falls_through_failures() -> None:
    unavailable = _StubProvider("off", available=False)
    failing = _StubProvider("flaky", error=RuntimeError("rate limited"))
    working = _StubProvider("good")
    never = _StubProvider("unused")
    chain = FallbackChainProvider([unavailable, failing, working, never])

    result = chain.analyze_completion("out", ["t"])

    assert result.provider_used == "good"
    assert (unavailable.calls, failing.calls, working.calls, never.calls) == (0, 1, 1, 0)
    assert chain.name == "fallback-chain(good)"


def test_chain_raises_with_last_error_when_every_provider_fails() -> None:
    chain = FallbackChainProvider(
        [_StubProvider("a", error=RuntimeError("first")), _StubProvider("b", error=OSError("last"))]
    )

    with pytest.raises(RuntimeError, match="All providers failed. Last error: last"):
        chain.analyze_completion("out", ["t"])


def test_chain_raises_when_no_provider_is_available() -> None:
    chain = FallbackChainProvider([_StubProvider("a", available=False)])

    with pytest.raises(RuntimeError, match="No providers available"):
        chain.analyze_completion("out", ["t"])


# ---------------------------------------------------------------------------
# Factory + CLI
# ---------------------------------------------------------------------------


def test_get_llm_provider_default_chain_order(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = get_llm_provider()

    assert isinstance(provider, FallbackChainProvider)
    assert [p.name for p in provider._providers] == ["github-models", "openai", "regex-fallback"]
    assert provider.is_available() is True  # regex fallback is always there


def test_get_llm_provider_rejects_unknown_forced_provider() -> None:
    with pytest.raises(ValueError, match="Unknown provider: gemini"):
        get_llm_provider("gemini")


def test_get_llm_provider_forced_regex_needs_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _unset_env(monkeypatch, *ENV_VARS)

    assert isinstance(get_llm_provider("regex-fallback"), RegexFallbackProvider)


def test_get_llm_provider_forced_provider_requires_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _unset_env(monkeypatch, "GITHUB_TOKEN", "OPENAI_API_KEY")

    with pytest.raises(RuntimeError, match="Forced provider 'openai' is not available"):
        get_llm_provider("openai")

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert isinstance(get_llm_provider("github-models"), GitHubModelsProvider)


def test_check_providers_reports_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    _unset_env(monkeypatch, "GITHUB_TOKEN", "OPENAI_API_KEY")
    assert check_providers() == {"github-models": False, "openai": False, "regex-fallback": True}

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert check_providers() == {"github-models": False, "openai": True, "regex-fallback": True}


def test_module_main_prints_availability_and_active_chain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _unset_env(monkeypatch, "GITHUB_TOKEN", "LANGSMITH_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    runpy.run_path(str(Path(lp.__file__)), run_name="__main__")

    out = capsys.readouterr().out
    assert "Provider availability:" in out
    assert "  ✗ github-models" in out
    assert "  ✓ openai" in out
    assert "  ✓ regex-fallback" in out
    assert "Active provider chain: fallback-chain" in out
