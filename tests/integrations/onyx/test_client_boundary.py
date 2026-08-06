from __future__ import annotations

import json

import pytest

from mnemosyne.integrations.onyx.client import (
    IngestResult,
    OnyxClient,
    PushStatus,
)


def test_t31_nonlocal_http_url_fails_before_socket_creation():
    with pytest.raises(ValueError, match="insecure_transport"):
        OnyxClient("http://example.invalid", "synthetic-key", 1)


def test_t32_host_outside_allowlist_is_rejected():
    with pytest.raises(ValueError, match="host_not_approved"):
        OnyxClient(
            "https://not-approved.invalid",
            "synthetic-key",
            1,
            allowed_hosts={"approved.invalid"},
        )


def test_t33_empty_host_allowlist_denies_client_creation():
    with pytest.raises(ValueError, match="approved_hosts_empty"):
        OnyxClient(
            "https://onyx.example.test",
            "synthetic-key",
            1,
            allowed_hosts=set(),
        )


def test_t34_localhost_http_is_an_explicit_safe_exception():
    client = OnyxClient("http://127.0.0.1:8080", "synthetic-key", 1)
    assert client.base_url == "http://127.0.0.1:8080"


def test_t35_api_key_is_absent_from_payload_and_client_log(monkeypatch, caplog):
    secret = "synthetic-secret-value"
    client = OnyxClient("https://onyx.example.test", secret, 7)
    captured: list[bytes] = []

    def fake_post(body: bytes, attempt: int) -> IngestResult:
        captured.append(body)
        return IngestResult("doc-35", PushStatus.ACCEPTED, status_code=200, attempts=attempt)

    monkeypatch.setattr(client, "_post", fake_post)
    client.ingest("doc-35", "[decision] test", "test", [{"text": "synthetic"}])
    assert captured
    assert secret not in captured[0].decode()
    assert secret not in caplog.text
    assert secret not in json.dumps(client._build_payload("id", "sid", "title", []))
