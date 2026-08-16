"""Contract §7 — environment-only tokens, redaction, and the live block."""

from __future__ import annotations

import logging

import pytest

from mnemosyne.integrations.slack.api import (
    DEFAULT_BASE_URL,
    SlackApiError,
    SlackLiveBlocked,
    WebApiConnector,
    is_loopback,
)
from mnemosyne.integrations.slack.config import (
    CODE_CREDENTIAL_MISSING,
    CODE_OVERBROAD_SCOPE,
    CODE_TOKEN_IN_CONFIG,
    DEFAULT_TOKEN_ENV,
    FORBIDDEN_SCOPES,
    REQUIRED_SCOPES,
    SlackConfig,
    SlackCredentialError,
    SlackScopeError,
    assert_scopes_allowed,
    parse_scope_header,
)
from mnemosyne.integrations.slack.redact import REDACTED, redact

FAKE_TOKEN = "xoxb-9999-FAKEFAKEFAKE"


# ── Token source ──────────────────────────────────────────────────────

def test_token_comes_only_from_the_environment(monkeypatch):
    monkeypatch.setenv(DEFAULT_TOKEN_ENV, FAKE_TOKEN)
    assert SlackConfig().resolve_token() == FAKE_TOKEN


def test_missing_token_is_a_hard_failure(monkeypatch):
    """T-CR-1 / R28: no partial or anonymous operation."""
    monkeypatch.delenv(DEFAULT_TOKEN_ENV, raising=False)
    with pytest.raises(SlackCredentialError) as exc:
        SlackConfig().resolve_token()
    assert exc.value.code == CODE_CREDENTIAL_MISSING


def test_blank_token_counts_as_missing(monkeypatch):
    monkeypatch.setenv(DEFAULT_TOKEN_ENV, "   ")
    with pytest.raises(SlackCredentialError) as exc:
        SlackConfig().resolve_token()
    assert exc.value.code == CODE_CREDENTIAL_MISSING


@pytest.mark.parametrize("key", ["token", "bot_token", "api_key", "secret"])
def test_config_carrying_a_token_is_refused(key):
    """T-CR-2: refused, not ignored — ignoring leaves the secret on disk."""
    with pytest.raises(SlackCredentialError) as exc:
        SlackConfig.from_dict({key: FAKE_TOKEN})
    assert exc.value.code == CODE_TOKEN_IN_CONFIG


def test_token_env_holding_a_value_is_refused():
    with pytest.raises(SlackCredentialError) as exc:
        SlackConfig.from_dict({"token_env": FAKE_TOKEN})
    assert exc.value.code == CODE_TOKEN_IN_CONFIG


def test_config_names_a_variable_and_loads_sources(tmp_path):
    path = tmp_path / "slack.yaml"
    path.write_text(
        "token_env: CUSTOM_SLACK_TOKEN\n"
        "sources:\n"
        "  - team_id: T1\n"
        "    channel_id: C1\n"
        "    scope_id: scope-a\n",
        encoding="utf-8",
    )
    config = SlackConfig.load(path)
    assert config.token_env == "CUSTOM_SLACK_TOKEN"
    assert config.sources[0].channel_id == "C1"
    assert config.sources[0].acl_mode == "require_snapshot"


def test_missing_config_file_reports_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        SlackConfig.load(tmp_path / "absent.yaml")


# ── Redaction ─────────────────────────────────────────────────────────

def test_redact_removes_token_shapes():
    """T-CR-3 / R29."""
    assert FAKE_TOKEN not in redact(f"Bearer {FAKE_TOKEN} failed")
    assert REDACTED in redact(f"Bearer {FAKE_TOKEN}")
    for prefix in ("xoxb", "xoxp", "xoxa", "xoxr", "xoxs", "xoxe"):
        assert prefix + "-" not in redact(f"{prefix}-123-abc")


def test_redact_leaves_ordinary_text_alone():
    assert redact("deny:acl_stale for C0FIXTURE1") == "deny:acl_stale for C0FIXTURE1"
    assert redact("") == ""


def test_exception_messages_are_redacted():
    """T-CR-6: the token must not ride along inside an error."""
    err = SlackApiError("invalid_auth", f"rejected token {FAKE_TOKEN}")
    assert FAKE_TOKEN not in str(err)
    cred = SlackCredentialError("blocked:credential_missing", f"env held {FAKE_TOKEN}")
    assert FAKE_TOKEN not in str(cred)


def test_adapter_logs_do_not_leak_the_token(caplog, monkeypatch):
    from mnemosyne.integrations.slack import api as api_mod

    caplog.set_level(logging.DEBUG, logger=api_mod.__name__)
    connector = WebApiConnector(FAKE_TOKEN, base_url="http://127.0.0.1:1/api",
                                max_retries=1, initial_backoff=0)
    with pytest.raises(SlackApiError):
        connector.channel_info("C1")
    assert FAKE_TOKEN not in caplog.text


# ── Scope enforcement ─────────────────────────────────────────────────

def test_minimum_scopes_are_allowed():
    assert_scopes_allowed(REQUIRED_SCOPES)


@pytest.mark.parametrize("scope", FORBIDDEN_SCOPES)
def test_each_forbidden_scope_is_refused(scope):
    """T-CR-4 / R30: over-permission is refused at the credential layer."""
    with pytest.raises(SlackScopeError) as exc:
        assert_scopes_allowed([*REQUIRED_SCOPES, scope])
    assert exc.value.code == CODE_OVERBROAD_SCOPE


def test_scope_header_parsing():
    assert parse_scope_header("a, b ,c") == ["a", "b", "c"]
    assert parse_scope_header(None) == []
    assert parse_scope_header("") == []


# ── Live block ────────────────────────────────────────────────────────

def test_loopback_detection():
    assert is_loopback("http://127.0.0.1:8080/api")
    assert is_loopback("http://localhost:9/api")
    assert not is_loopback(DEFAULT_BASE_URL)


def test_real_slack_is_blocked_without_approval():
    """T-CR-5 (core) / R31: this is the contract, not a defect."""
    connector = WebApiConnector(FAKE_TOKEN)
    for call in (
        lambda: connector.channel_info("C1"),
        lambda: list(connector.history("C1")),
        lambda: list(connector.replies("C1", "1712345678.000100")),
    ):
        with pytest.raises(SlackLiveBlocked) as exc:
            call()
        assert exc.value.code == "blocked:live_not_approved"


def test_loopback_is_not_blocked():
    """The guard must not also block the mock server."""
    connector = WebApiConnector(
        FAKE_TOKEN, base_url="http://127.0.0.1:1/api", max_retries=1,
        initial_backoff=0,
    )
    # Reaches the transport (and fails to connect) rather than being blocked.
    with pytest.raises(SlackApiError) as exc:
        connector.channel_info("C1")
    assert not isinstance(exc.value, SlackLiveBlocked)


def test_adapter_requires_a_token():
    with pytest.raises(SlackApiError) as exc:
        WebApiConnector("")
    assert exc.value.code == "blocked:credential_missing"
