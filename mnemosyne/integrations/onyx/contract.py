"""Common data contract for Onyx ↔ Mnemosyne sync.

Defines the Envelope — the canonical interchange format for documents
crossing the integration boundary in either direction — plus the
stable-identifier rules that guarantee:

1. Same document re-collected keeps the same ID (no duplicates).
2. Same content hash is a no-op.
3. Changed content produces a new version; old version is never deleted.
4. Provenance (external_uri, source ID, revision) is preserved.
5. Deletion is tombstone + ``valid_to``, never physical.
6. Mnemosyne-generated documents are marked ``do_not_reimport`` to
   prevent push→export infinite loops.
7. ACL-unverifiable documents are quarantined, never auto-promoted.

See: docs/ONYX_MNEMOSYNE_INTEGRATION_PLAN.ko.md §3 (공통 데이터 계약).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

# ── Bump when the Envelope shape changes incompatibly. ──────────────
CONTRACT_VERSION = "1.0"

# Entity types eligible for Onyx publication (Phase 1 principle:
# curated knowledge only, not raw dumps).
PUBLISHABLE_ENTITY_TYPES = frozenset({
    "project",
    "requirement",
    "decision",
    "meeting",
    "action-item",
    "risk",
    "conflict",
    "release",
})

# Classification levels, ordered most→least restrictive.
_CLASSIFICATION_ORDER = ("private", "confidential", "internal", "public")


class SyncOrigin(str, Enum):
    """Which system originated the document."""

    ONYX = "onyx"
    MNEMOSYNE = "mnemosyne"
    MANUAL = "manual"


class Visibility(str, Enum):
    """Scope of visibility for a document."""

    PRIVATE = "private"        # owner only
    PROJECT = "project"        # project scope members
    ORGANIZATION = "org"       # org-wide
    PUBLIC = "public"


class EnvelopeError(ValueError):
    """Raised when an Envelope violates the data contract."""


# ── Stable identifier rules (§3 식별자 규칙) ─────────────────────────

# Characters that are illegal in stable-ID segments; replaced with ``-``.
# ``:`` is the format separator and is kept; ``/`` is rejected to keep
# IDs path-safe and filesystem-clean.
_ID_SANITIZER = re.compile(r"[^A-Za-z0-9._:-]")


def _sanitize(value: str) -> str:
    """Collapse an arbitrary string into a stable-ID-safe segment."""
    cleaned = _ID_SANITIZER.sub("-", str(value)).strip("-")
    return cleaned or "_"


def source_document_id(connector_id: str, external_document_id: str) -> str:
    """Canonical ID for an Onyx-sourced document.

    Format: ``onyx:{connector_id}:{external_document_id}``

    The same connector + external document always yields the same ID,
    regardless of section order or collection timing.
    """
    if not connector_id:
        raise EnvelopeError("connector_id is required for source_document_id")
    if not external_document_id:
        raise EnvelopeError(
            "external_document_id is required for source_document_id"
        )
    return f"onyx:{_sanitize(connector_id)}:{_sanitize(external_document_id)}"


def mnemosyne_source_id(
    source_doc_id: str, revision: Optional[str] = None
) -> str:
    """Mnemosyne-internal source ID = source doc ID + revision or hash.

    When *revision* is available it anchors a specific version of the
    source; otherwise the content hash distinguishes versions.
    """
    if not source_doc_id:
        raise EnvelopeError("source_doc_id is required for mnemosyne_source_id")
    suffix = _sanitize(revision) if revision else "latest"
    return f"{source_doc_id}#{suffix}"


def entity_stable_id(
    scope_id: str, entity_type: str, canonical_name: str
) -> str:
    """Deterministic entity ID within a scope.

    Format: ``{scope_id}:{entity_type}:{canonical_name}``

    Two extractions of the same conceptual entity in the same scope
    converge on the same ID, enabling idempotent upserts.
    """
    for name, val in (
        ("scope_id", scope_id),
        ("entity_type", entity_type),
        ("canonical_name", canonical_name),
    ):
        if not val:
            raise EnvelopeError(f"{name} is required for entity_stable_id")
    return f"{_sanitize(scope_id)}:{_sanitize(entity_type)}:{_sanitize(canonical_name)}"


def onyx_publish_id(scope_id: str, entity_type: str, entity_id: str) -> str:
    """Stable document ID when Mnemosyne pushes curated knowledge to Onyx.

    Format: ``mnemosyne:{scope_id}:{entity_type}:{entity_id}``

    This is the ``document.id`` sent to the Onyx Ingestion API so that
    re-publishing the same entity is an update, not a duplicate.
    """
    for name, val in (
        ("scope_id", scope_id),
        ("entity_type", entity_type),
        ("entity_id", entity_id),
    ):
        if not val:
            raise EnvelopeError(f"{name} is required for onyx_publish_id")
    return (
        f"mnemosyne:{_sanitize(scope_id)}"
        f":{_sanitize(entity_type)}:{_sanitize(entity_id)}"
    )


# ── Content hashing ─────────────────────────────────────────────────

def compute_content_hash(sections: list[dict[str, Any]]) -> str:
    """SHA-256 of normalized section text.

    Normalization strips trailing whitespace and sorts sections by text
    so that re-ordering or whitespace-only changes are no-ops.
    """
    normalized = sorted(
        (str(s.get("text", "")).rstrip() for s in sections),
    )
    payload = "\n".join(normalized).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"sha256:{digest}"


# ── Envelope ────────────────────────────────────────────────────────

@dataclass
class AccessSnapshot:
    """ACL snapshot captured at collection time.

    When ``acl_mode`` is ``require_snapshot`` and this is empty/stale,
    the document is quarantined rather than auto-promoted.
    """

    users: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    captured_at: Optional[str] = None  # ISO-8601; None = unknown freshness

    def is_empty(self) -> bool:
        return not self.users and not self.groups

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "AccessSnapshot":
        if not data:
            return cls()
        return cls(
            users=list(data.get("users", [])),
            groups=list(data.get("groups", [])),
            captured_at=data.get("captured_at"),
        )


@dataclass
class Envelope:
    """Canonical interchange document for the Onyx↔Mnemosyne boundary.

    This is the Envelope defined in §3.1 of the integration plan. It is
    the single contract every Export Worker emission and every Push
    Adapter output must satisfy.
    """

    # ── Origin tracking ──
    source_system: str = "onyx"
    source_type: str = ""                # github, slack, gmail, file, ...
    onyx_connector_id: str = ""
    onyx_cc_pair_id: Optional[int] = None

    # ── External identity ──
    external_document_id: str = ""
    external_revision: str = ""
    external_uri: str = ""

    # ── Content ──
    title: str = ""
    sections: list[dict[str, Any]] = field(default_factory=list)

    # ── Temporal ──
    source_updated_at: str = ""          # when the source last changed
    captured_at: str = ""                # when Mnemosyne collected it

    # ── Integrity ──
    content_hash: str = ""

    # ── Mnemosyne routing ──
    scope_id: str = ""
    source_channel: str = ""
    visibility: Visibility = Visibility.PROJECT
    classification: str = "internal"     # private|confidential|internal|public

    # ── Access control ──
    access_snapshot: AccessSnapshot = field(default_factory=AccessSnapshot)

    # ── Sync metadata ──
    sync_origin: SyncOrigin = SyncOrigin.ONYX
    do_not_reimport: bool = False

    # ── Contract version ──
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        # Normalize enum fields that may arrive as plain strings.
        if isinstance(self.visibility, str):
            self.visibility = Visibility(self.visibility)
        if isinstance(self.sync_origin, str):
            self.sync_origin = SyncOrigin(self.sync_origin)
        if isinstance(self.access_snapshot, dict):
            self.access_snapshot = AccessSnapshot.from_dict(
                self.access_snapshot
            )
        # Auto-fill captured_at if missing.
        if not self.captured_at:
            self.captured_at = datetime.now(timezone.utc).isoformat()
        # Auto-fill content_hash if sections are present.
        if self.sections and not self.content_hash:
            self.content_hash = compute_content_hash(self.sections)

    # ── Derived IDs ──

    @property
    def source_doc_id(self) -> str:
        """The stable Onyx-side document identifier."""
        return source_document_id(
            self.onyx_connector_id, self.external_document_id
        )

    @property
    def mnemosyne_source_id(self) -> str:
        """The Mnemosyne-internal source version identifier."""
        return mnemosyne_source_id(
            self.source_doc_id,
            self.external_revision or self.content_hash,
        )

    @property
    def needs_quarantine(self) -> bool:
        """True when ACL cannot be verified (§3 rule 7)."""
        return self.access_snapshot.is_empty()

    # ── Serialization ──

    def to_dict(self) -> dict[str, Any]:
        """Full dict representation for JSON serialization."""
        return {
            "contract_version": self.contract_version,
            "source_system": self.source_system,
            "source_type": self.source_type,
            "onyx_connector_id": self.onyx_connector_id,
            "onyx_cc_pair_id": self.onyx_cc_pair_id,
            "external_document_id": self.external_document_id,
            "external_revision": self.external_revision,
            "external_uri": self.external_uri,
            "title": self.title,
            "sections": self.sections,
            "source_updated_at": self.source_updated_at,
            "captured_at": self.captured_at,
            "content_hash": self.content_hash,
            "scope_id": self.scope_id,
            "source_channel": self.source_channel,
            "visibility": self.visibility.value,
            "classification": self.classification,
            "access_snapshot": self.access_snapshot.to_dict(),
            "sync_origin": self.sync_origin.value,
            "do_not_reimport": self.do_not_reimport,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Envelope":
        """Construct from a parsed JSON dict, tolerant of missing fields."""
        known = {
            k: v for k, v in data.items()
            if k in cls.__dataclass_fields__  # type: ignore[attr-defined]
        }
        return cls(**known)


# ── Validation ──────────────────────────────────────────────────────

# Required fields for a well-formed Envelope.
_REQUIRED_FIELDS = (
    "source_system",
    "external_document_id",
    "title",
    "sections",
    "scope_id",
    "source_channel",
    "content_hash",
    "captured_at",
)


def validate_envelope(env: Envelope) -> list[str]:
    """Validate an Envelope against the data contract.

    Returns a list of error messages (empty = valid). Does not raise;
    callers decide whether errors are hard failures or quarantine
    candidates based on context.
    """
    errors: list[str] = []

    if env.contract_version != CONTRACT_VERSION:
        errors.append(
            f"contract_version mismatch: expected {CONTRACT_VERSION!r}, "
            f"got {env.contract_version!r}"
        )

    # Onyx-sourced documents need connector identity.
    if env.source_system == "onyx":
        if not env.onyx_connector_id:
            errors.append("onyx-sourced envelope missing onyx_connector_id")
        if env.onyx_cc_pair_id is None:
            errors.append("onyx-sourced envelope missing onyx_cc_pair_id")

    if not env.external_document_id:
        errors.append("external_document_id is required")

    if not env.title.strip():
        errors.append("title is required (non-empty)")

    if not env.sections:
        errors.append("sections must be non-empty")
    else:
        for i, sec in enumerate(env.sections):
            if "text" not in sec or not str(sec["text"]).strip():
                errors.append(f"sections[{i}] missing non-empty 'text'")

    if not env.scope_id:
        errors.append("scope_id is required")

    if not env.source_channel:
        errors.append("source_channel is required")

    # Content hash must match recomputed hash (detects tampering / drift).
    if env.sections:
        recomputed = compute_content_hash(env.sections)
        if env.content_hash and env.content_hash != recomputed:
            errors.append(
                f"content_hash mismatch: envelope has {env.content_hash!r} "
                f"but recomputed {recomputed!r}"
            )

    if env.classification not in _CLASSIFICATION_ORDER:
        errors.append(
            f"classification {env.classification!r} not in "
            f"{_CLASSIFICATION_ORDER}"
        )

    # Mnemosyne-generated documents must be marked to prevent loops.
    if (
        env.sync_origin == SyncOrigin.MNEMOSYNE
        and not env.do_not_reimport
    ):
        errors.append(
            "sync_origin=mnemosyne requires do_not_reimport=true "
            "(prevents push→export loop)"
        )

    return errors
