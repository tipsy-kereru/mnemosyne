"""HTTP client for the Onyx Ingestion API.

Wraps the POST /onyx-api/ingestion endpoint with:
- Bearer-token authentication (key resolved from env at call time).
- Exponential-backoff retry on transient errors (429, 5xx, timeout).
- Error classification: rate_limit, timeout, auth, server, client.
- Never logs the API key or document content (redaction contract §3 rule 8).

Uses ``urllib`` from the standard library to avoid adding a hard
dependency on ``requests``; falls back to ``requests`` when available
for connection-pooling benefits.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

INGESTION_PATH = "/onyx-api/ingestion"
DEFAULT_TIMEOUT = 30  # seconds


class PushStatus(str, Enum):
    ACCEPTED = "accepted"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    AUTH_ERROR = "auth_error"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"


class OnyxClientError(Exception):
    """Base error for Onyx client failures."""

    def __init__(self, status: PushStatus, message: str, status_code: int = 0):
        self.push_status = status
        self.status_code = status_code
        super().__init__(message)


@dataclass
class IngestResult:
    """Result of a single document ingestion call."""

    document_id: str
    status: PushStatus
    status_code: int = 0
    message: str = ""
    attempts: int = 0


class OnyxClient:
    """Thin client for the Onyx Ingestion API.

    Args:
        base_url: e.g. ``https://cloud.onyx.app`` (no trailing slash).
        api_key: Bearer token. Resolved by the caller from the env.
        cc_pair_id: Connector-credential pair to associate documents with.
        timeout: Per-request timeout in seconds.
        max_retries: Max retry attempts on transient errors.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        cc_pair_id: int,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = 5,
        initial_backoff: float = 5.0,
        backoff_multiplier: float = 2.0,
        allowed_hosts: Optional[set[str]] = None,
    ) -> None:
        if not base_url:
            raise ValueError("OnyxClient requires base_url")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("deny:insecure_transport")
        if parsed.scheme != "https" and parsed.hostname not in {
            "localhost", "127.0.0.1", "::1"
        }:
            raise ValueError("deny:insecure_transport: requires https")
        if allowed_hosts is not None:
            if not allowed_hosts:
                raise ValueError("deny:approved_hosts_empty")
            if parsed.hostname not in allowed_hosts:
                raise ValueError("deny:host_not_approved")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.cc_pair_id = cc_pair_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.backoff_multiplier = backoff_multiplier

    @property
    def _url(self) -> str:
        return f"{self.base_url}{INGESTION_PATH}"

    def _build_payload(
        self,
        document_id: str,
        semantic_identifier: str,
        title: str,
        sections: list[dict[str, Any]],
        metadata: Optional[dict[str, Any]] = None,
        doc_updated_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Build the Onyx IngestionDocument payload."""
        document: dict[str, Any] = {
            "id": document_id,
            "semantic_identifier": semantic_identifier,
            "title": title,
            "sections": sections,
            "source": "mnemosyne",
            "from_ingestion_api": True,
        }
        if metadata:
            document["metadata"] = metadata
        if doc_updated_at:
            document["doc_updated_at"] = doc_updated_at
        return {"document": document, "cc_pair_id": self.cc_pair_id}

    def ingest(
        self,
        document_id: str,
        semantic_identifier: str,
        title: str,
        sections: list[dict[str, Any]],
        metadata: Optional[dict[str, Any]] = None,
        doc_updated_at: Optional[str] = None,
    ) -> IngestResult:
        """Push a single document to Onyx with retry.

        Returns an :class:`IngestResult`. Raises only on programming
        errors (missing key); transient failures are retried then
        returned as a non-ACCEPTED result.
        """
        if not self.api_key:
            raise OnyxClientError(
                PushStatus.AUTH_ERROR, "API key not provided"
            )

        payload = self._build_payload(
            document_id, semantic_identifier, title,
            sections, metadata, doc_updated_at,
        )
        body = json.dumps(payload).encode("utf-8")

        backoff = self.initial_backoff
        last_result = IngestResult(
            document_id=document_id, status=PushStatus.CLIENT_ERROR
        )

        for attempt in range(1, self.max_retries + 1):
            last_result.attempts = attempt
            try:
                result = self._post(body, attempt)
                if result.status == PushStatus.ACCEPTED:
                    return result
                # Non-accepted: decide whether to retry.
                if not self._is_retryable(result.status):
                    return result
                last_result = result
            except OnyxClientError as exc:
                last_result = IngestResult(
                    document_id=document_id,
                    status=exc.push_status,
                    status_code=exc.status_code,
                    message=str(exc),
                    attempts=attempt,
                )
                if not self._is_retryable(exc.push_status):
                    return last_result

            if attempt < self.max_retries:
                logger.info(
                    "Onyx ingest attempt %d for %s failed (%s); "
                    "retrying in %.1fs",
                    attempt, document_id, last_result.status.value, backoff,
                )
                time.sleep(backoff)
                backoff *= self.backoff_multiplier

        logger.warning(
            "Onyx ingest exhausted %d attempts for %s",
            self.max_retries, document_id,
        )

    def withdraw(self, document_id: str) -> IngestResult:
        """Withdraw one document using the destination DELETE boundary."""
        if not self.api_key:
            raise OnyxClientError(
                PushStatus.AUTH_ERROR, "API key not provided"
            )
        request = urllib.request.Request(
            f"{self.base_url}{INGESTION_PATH}/{document_id}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return IngestResult(
                    document_id=document_id,
                    status=(
                        PushStatus.ACCEPTED
                        if 200 <= resp.status < 300
                        else PushStatus.CLIENT_ERROR
                    ),
                    status_code=resp.status,
                    attempts=1,
                )
        except urllib.error.HTTPError as exc:
            return IngestResult(
                document_id=document_id,
                status=PushStatus.CLIENT_ERROR,
                status_code=exc.code,
                message=f"Withdrawal failed: {exc.reason}",
                attempts=1,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return IngestResult(
                document_id=document_id,
                status=PushStatus.TIMEOUT,
                message=f"Withdrawal connection error: {exc}",
                attempts=1,
            )
        return last_result

    def _post(self, body: bytes, attempt: int) -> IngestResult:
        """Single HTTP POST; classifies the response."""
        doc_id = json.loads(body)["document"]["id"]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(
            self._url, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status_code = resp.status
        except urllib.error.HTTPError as exc:
            return self._classify_http_error(doc_id, exc, attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OnyxClientError(
                PushStatus.TIMEOUT,
                f"Connection error: {exc}",
            ) from exc

        if 200 <= status_code < 300:
            return IngestResult(
                document_id=doc_id,
                status=PushStatus.ACCEPTED,
                status_code=status_code,
                attempts=attempt,
            )
        # Shouldn't reach here for 2xx, but handle defensively.
        return IngestResult(
            document_id=doc_id,
            status=PushStatus.SERVER_ERROR,
            status_code=status_code,
            attempts=attempt,
        )

    def _classify_http_error(
        self, doc_id: str, exc: urllib.error.HTTPError, attempt: int
    ) -> IngestResult:
        code = exc.code
        if code == 401 or code == 403:
            return IngestResult(
                document_id=doc_id,
                status=PushStatus.AUTH_ERROR,
                status_code=code,
                message=f"Auth failed: {exc.reason}",
                attempts=attempt,
            )
        if code == 429:
            return IngestResult(
                document_id=doc_id,
                status=PushStatus.RATE_LIMITED,
                status_code=code,
                message="Rate limited",
                attempts=attempt,
            )
        if 500 <= code < 600:
            return IngestResult(
                document_id=doc_id,
                status=PushStatus.SERVER_ERROR,
                status_code=code,
                message=f"Server error: {exc.reason}",
                attempts=attempt,
            )
        return IngestResult(
            document_id=doc_id,
            status=PushStatus.CLIENT_ERROR,
            status_code=code,
            message=f"Client error: {exc.reason}",
            attempts=attempt,
        )

    @staticmethod
    def _is_retryable(status: PushStatus) -> bool:
        """Rate limits and server errors are retryable; auth/client are not."""
        return status in (PushStatus.RATE_LIMITED, PushStatus.SERVER_ERROR,
                          PushStatus.TIMEOUT)
