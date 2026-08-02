"""Contract tests for the Onyx ↔ Mnemosyne Envelope.

Implements the test strategy from §8 of the integration plan:

- Contract tests: required fields, type validation, stable ID
  independence from section order, same content_hash no-op, unknown
  contract_version quarantine/fail.
- State transition tests: covered in test_state_machine.py.
- Permission tests: covered in test_acl.py.
"""

import json
from datetime import datetime, timezone

import pytest

from mnemosyne.integrations.onyx.contract import (
    CONTRACT_VERSION,
    AccessSnapshot,
    Envelope,
    EnvelopeError,
    SyncOrigin,
    Visibility,
    compute_content_hash,
    entity_stable_id,
    onyx_publish_id,
    source_document_id,
    mnemosyne_source_id,
    validate_envelope,
)
from mnemosyne.integrations.onyx.config import SyncConfig


# ── Helpers ─────────────────────────────────────────────────────────

def _valid_envelope(**overrides) -> Envelope:
    """Build a well-formed Envelope with sensible defaults."""
    base = dict(
        source_system="onyx",
        source_type="github",
        onyx_connector_id="connector-17",
        onyx_cc_pair_id=243,
        external_document_id="github:acme/widgets:issue:193",
        external_revision="rev-abc",
        external_uri="https://github.com/acme/widgets/issues/193",
        title="인증 방식 결정",
        sections=[
            {"text": "OAuth 2.0 with PKCE를 사용하기로 결정했다.", "link": "https://github.com/acme/widgets/issues/193"},
        ],
        source_updated_at="2026-08-02T10:20:00Z",
        scope_id="client-a",
        source_channel="github",
        classification="internal",
        access_snapshot=AccessSnapshot(
            users=["alice@example.com"],
            groups=["project-client-a"],
            captured_at=datetime.now(timezone.utc).isoformat(),
        ),
    )
    base.update(overrides)
    return Envelope(**base)


# ── Stable ID tests (§3 식별자 규칙) ────────────────────────────────

class TestStableIDs:
    """Same logical document always yields the same ID."""

    def test_source_document_id_is_deterministic(self):
        a = source_document_id("connector-17", "github:org/repo:issue:193")
        b = source_document_id("connector-17", "github:org/repo:issue:193")
        assert a == b
        assert a == "onyx:connector-17:github:org-repo:issue:193"

    def test_source_document_id_different_connectors(self):
        a = source_document_id("connector-17", "doc-1")
        b = source_document_id("connector-18", "doc-1")
        assert a != b

    def test_source_document_id_rejects_empty(self):
        with pytest.raises(EnvelopeError):
            source_document_id("", "doc-1")
        with pytest.raises(EnvelopeError):
            source_document_id("connector-1", "")

    def test_entity_stable_id_is_deterministic(self):
        a = entity_stable_id("client-a", "decision", "use-oauth-pkce")
        b = entity_stable_id("client-a", "decision", "use-oauth-pkce")
        assert a == b
        assert a == "client-a:decision:use-oauth-pkce"

    def test_entity_stable_id_scope_isolated(self):
        """Same entity name in different scopes is different."""
        personal = entity_stable_id("personal", "decision", "use-oauth-pkce")
        client = entity_stable_id("client-a", "decision", "use-oauth-pkce")
        assert personal != client

    def test_onyx_publish_id_format(self):
        pub_id = onyx_publish_id("client-a", "decision", "client-a:decision:use-oauth-pkce")
        assert pub_id.startswith("mnemosyne:client-a:decision:")

    def test_mnemosyne_source_id_with_revision(self):
        doc_id = source_document_id("c1", "doc-1")
        src_id = mnemosyne_source_id(doc_id, "rev-2")
        assert src_id == f"{doc_id}#rev-2"

    def test_mnemosyne_source_id_without_revision(self):
        doc_id = source_document_id("c1", "doc-1")
        src_id = mnemosyne_source_id(doc_id)
        assert src_id == f"{doc_id}#latest"

    def test_id_sanitizes_unsafe_chars(self):
        """Path separators and special chars are normalized."""
        sid = source_document_id("conn/evil", "doc\x00mal")
        assert "/" not in sid
        assert "\x00" not in sid


# ── Content hash tests (§3 rule 2: same hash = no-op) ──────────────

class TestContentHash:
    def test_same_content_same_hash(self):
        sections = [{"text": "hello"}, {"text": "world"}]
        assert compute_content_hash(sections) == compute_content_hash(sections)

    def test_section_reorder_same_hash(self):
        """Reordering sections must not change the hash (no-op)."""
        a = compute_content_hash([{"text": "first"}, {"text": "second"}])
        b = compute_content_hash([{"text": "second"}, {"text": "first"}])
        assert a == b

    def test_whitespace_only_change_same_hash(self):
        """Trailing whitespace differences are normalized away."""
        a = compute_content_hash([{"text": "content   "}])
        b = compute_content_hash([{"text": "content"}])
        assert a == b

    def test_different_content_different_hash(self):
        a = compute_content_hash([{"text": "decision A"}])
        b = compute_content_hash([{"text": "decision B"}])
        assert a != b

    def test_hash_prefix(self):
        h = compute_content_hash([{"text": "x"}])
        assert h.startswith("sha256:")


# ── Envelope validation tests (§8 계약 테스트) ─────────────────────

class TestEnvelopeValidation:
    def test_valid_envelope_no_errors(self):
        env = _valid_envelope()
        assert validate_envelope(env) == []

    def test_missing_title(self):
        env = _valid_envelope(title="")
        errors = validate_envelope(env)
        assert any("title" in e for e in errors)

    def test_missing_scope_id(self):
        env = _valid_envelope(scope_id="")
        errors = validate_envelope(env)
        assert any("scope_id" in e for e in errors)

    def test_empty_sections(self):
        env = _valid_envelope(sections=[])
        errors = validate_envelope(env)
        assert any("sections" in e for e in errors)

    def test_section_missing_text(self):
        env = _valid_envelope(sections=[{"link": "https://..."}])
        errors = validate_envelope(env)
        assert any("sections[0]" in e for e in errors)

    def test_unknown_contract_version(self):
        """Unknown contract_version must produce an error (§8)."""
        env = _valid_envelope()
        env.contract_version = "999.0"
        errors = validate_envelope(env)
        assert any("contract_version" in e for e in errors)

    def test_onyx_missing_connector_id(self):
        env = _valid_envelope(onyx_connector_id="")
        errors = validate_envelope(env)
        assert any("connector_id" in e for e in errors)

    def test_content_hash_mismatch_detected(self):
        """Tampered hash is caught (§8: content_hash no-op validation)."""
        env = _valid_envelope()
        env.content_hash = "sha256:deadbeef"
        errors = validate_envelope(env)
        assert any("content_hash mismatch" in e for e in errors)

    def test_invalid_classification(self):
        env = _valid_envelope(classification="top-secret")
        errors = validate_envelope(env)
        assert any("classification" in e for e in errors)


# ── Loop prevention (§3 rule 6, §9 위험) ────────────────────────────

class TestLoopPrevention:
    def test_mnemosyne_origin_must_not_reimport(self):
        """sync_origin=mnemosyne without do_not_reimport is an error."""
        env = _valid_envelope(
            sync_origin=SyncOrigin.MNEMOSYNE,
            do_not_reimport=False,
        )
        errors = validate_envelope(env)
        assert any("do_not_reimport" in e for e in errors)

    def test_mnemosyne_origin_with_reimport_flag_is_ok(self):
        env = _valid_envelope(
            sync_origin=SyncOrigin.MNEMOSYNE,
            do_not_reimport=True,
        )
        errors = validate_envelope(env)
        assert not any("do_not_reimport" in e for e in errors)


# ── Serialization round-trip ────────────────────────────────────────

class TestSerialization:
    def test_roundtrip_preserves_all_fields(self):
        env = _valid_envelope()
        d = env.to_dict()
        restored = Envelope.from_dict(d)
        assert restored.title == env.title
        assert restored.scope_id == env.scope_id
        assert restored.content_hash == env.content_hash
        assert restored.sync_origin == env.sync_origin
        assert restored.access_snapshot.users == env.access_snapshot.users

    def test_to_json_is_valid_json(self):
        env = _valid_envelope()
        parsed = json.loads(env.to_json())
        assert parsed["contract_version"] == CONTRACT_VERSION
        assert parsed["scope_id"] == "client-a"

    def test_from_dict_ignores_unknown_fields(self):
        """Forward-compatible: unknown keys don't break parsing."""
        env = _valid_envelope()
        d = env.to_dict()
        d["future_field"] = "ignored"
        restored = Envelope.from_dict(d)
        assert restored.title == env.title


# ── Derived properties ──────────────────────────────────────────────

class TestDerivedProperties:
    def test_source_doc_id_from_envelope(self):
        env = _valid_envelope()
        expected = source_document_id(
            env.onyx_connector_id, env.external_document_id
        )
        assert env.source_doc_id == expected

    def test_needs_quarantine_when_acl_empty(self):
        env = _valid_envelope(
            access_snapshot=AccessSnapshot()
        )
        assert env.needs_quarantine is True

    def test_does_not_need_quarantine_with_acl(self):
        env = _valid_envelope()
        assert env.needs_quarantine is False

    def test_auto_content_hash_on_construction(self):
        """Sections present but no hash → auto-computed."""
        env = _valid_envelope(content_hash="")
        assert env.content_hash.startswith("sha256:")


# ── Config loading tests ────────────────────────────────────────────

class TestSyncConfig:
    def test_load_from_yaml_dict(self):
        cfg = SyncConfig.from_dict({
            "version": 1,
            "onyx": {
                "base_url": "https://onyx.example.com",
                "api_key_env": "ONYX_API_KEY",
                "cc_pair_id_env": "ONYX_CC_PAIR",
            },
            "mappings": [
                {
                    "connector_id": "client-a-github",
                    "scope_id": "client-a",
                    "source_channel": "github",
                    "default_classification": "confidential",
                    "acl_mode": "require_snapshot",
                },
            ],
            "sync": {
                "max_attempts": 3,
                "initial_backoff_seconds": 2,
            },
        })
        assert cfg.onyx.base_url == "https://onyx.example.com"
        assert cfg.onyx.api_key_env == "ONYX_API_KEY"
        m = cfg.mapping_for_connector("client-a-github")
        assert m is not None
        assert m.scope_id == "client-a"
        assert m.default_classification == "confidential"
        assert cfg.sync.max_attempts == 3
        assert cfg.sync.deletion_policy == "tombstone"

    def test_mapping_lookup_returns_none_for_unknown(self):
        cfg = SyncConfig()
        assert cfg.mapping_for_connector("nope") is None

    def test_config_rejects_missing_file(self):
        from mnemosyne.integrations.onyx.config import ConfigError
        with pytest.raises(ConfigError):
            SyncConfig.load("/nonexistent/path.yaml")
