"""Token-budget tests for LLMBridge._max_tokens() — finishes the WIP that made
per-request output token limits env-configurable (MNEMOSYNE_LLM_MAX_TOKENS).

The 8192 default unifies what were previously provider-specific limits
(anthropic=2048, openai=2048, zai=8192). The lower 2048 values truncated
extraction JSON, which is exactly what LLMBridge._parse_json.try_repair
exists to recover from; raising the default reduces truncation upstream.
"""

from __future__ import annotations

import importlib
import logging

import pytest


def _import_bridge():
    return importlib.import_module("mnemosyne.ingest.llm_bridge")


class TestMaxTokens:
    """_max_tokens() env parsing, validation, and fallback."""

    @pytest.fixture(autouse=True)
    def _clear_token_env(self, monkeypatch):
        monkeypatch.delenv("MNEMOSYNE_LLM_MAX_TOKENS", raising=False)

    def test_default_when_unset(self):
        bridge = _import_bridge()
        assert bridge._max_tokens() == bridge.DEFAULT_LLM_MAX_TOKENS
        assert bridge.DEFAULT_LLM_MAX_TOKENS > 0

    def test_env_override_valid(self, monkeypatch):
        bridge = _import_bridge()
        monkeypatch.setenv("MNEMOSYNE_LLM_MAX_TOKENS", "4096")
        assert bridge._max_tokens() == 4096

    def test_env_override_strips_whitespace(self, monkeypatch):
        bridge = _import_bridge()
        # int() tolerates surrounding whitespace; document the behaviour.
        monkeypatch.setenv("MNEMOSYNE_LLM_MAX_TOKENS", " 4096 ")
        assert bridge._max_tokens() == 4096

    def test_env_invalid_logs_warning_and_falls_back(self, monkeypatch, caplog):
        bridge = _import_bridge()
        monkeypatch.setenv("MNEMOSYNE_LLM_MAX_TOKENS", "not-a-number")
        with caplog.at_level(logging.WARNING, logger="mnemosyne.ingest.llm_bridge"):
            result = bridge._max_tokens()
        assert result == bridge.DEFAULT_LLM_MAX_TOKENS
        assert any("MNEMOSYNE_LLM_MAX_TOKENS" in rec.message for rec in caplog.records)

    def test_env_zero_falls_back(self, monkeypatch):
        bridge = _import_bridge()
        monkeypatch.setenv("MNEMOSYNE_LLM_MAX_TOKENS", "0")
        # Zero is not a positive budget; reject and use the default.
        assert bridge._max_tokens() == bridge.DEFAULT_LLM_MAX_TOKENS

    def test_env_negative_falls_back(self, monkeypatch):
        bridge = _import_bridge()
        monkeypatch.setenv("MNEMOSYNE_LLM_MAX_TOKENS", "-100")
        assert bridge._max_tokens() == bridge.DEFAULT_LLM_MAX_TOKENS

    def test_env_empty_string_falls_back(self, monkeypatch):
        bridge = _import_bridge()
        monkeypatch.setenv("MNEMOSYNE_LLM_MAX_TOKENS", "")
        assert bridge._max_tokens() == bridge.DEFAULT_LLM_MAX_TOKENS


class TestProviderWiring:
    """Each SDK-backed provider must thread the configured budget through."""

    def test_all_providers_reference_max_tokens(self):
        """Static guard: the four SDK providers route output budget via _max_tokens().

        The CLI provider intentionally has no token parameter. This guards against
        a future refactor dropping the wiring on one of the SDK paths.
        """
        bridge = _import_bridge()
        import inspect

        for provider_method in ("_call_zai", "_call_anthropic", "_call_openai", "_call_google"):
            method_src = inspect.getsource(getattr(bridge.LLMBridge, provider_method))
            assert "_max_tokens()" in method_src, f"{provider_method} lost its _max_tokens() wiring"
        # CLI must NOT carry a token arg (it shells out; budget is OS/process-level).
        assert "_max_tokens" not in inspect.getsource(bridge.LLMBridge._call_cli)
