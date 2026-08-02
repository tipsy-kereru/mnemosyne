"""Onyx ↔ Mnemosyne bidirectional sync integration.

Architecture (see docs/ONYX_MNEMOSYNE_INTEGRATION_PLAN.ko.md):

    Onyx: auth · connectors · source search · user permissions
        ↕  Export Worker / Push Adapter
    Mnemosyne: provenance · scope isolation · entity/relation graph
        · temporal history · tombstone · wiki · review queue

This package implements the contract boundary defined in
``contract.py`` — the Envelope schema and stable-ID rules that keep
both directions idempotent, lossless, and loop-free.
"""

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
    validate_envelope,
)
from mnemosyne.integrations.onyx.client import (
    IngestResult,
    OnyxClient,
    OnyxClientError,
    PushStatus,
)
from mnemosyne.integrations.onyx.mapper import MapResult, map_entity
from mnemosyne.integrations.onyx.sync_state import PushState, SyncStateStore
from mnemosyne.integrations.onyx.exporter import OnyxPushExporter, PushOutcome
from mnemosyne.integrations.onyx.checkpoint import Checkpoint, CheckpointStore
from mnemosyne.integrations.onyx.worker import (
    BatchResult,
    ExportWorker,
    ProcessResult,
)
from mnemosyne.integrations.onyx.permissions import (
    Provenance,
    can_access,
    classification_rank,
    enrich_results_with_provenance,
    extract_provenance,
    filter_by_classification,
    requires_review,
)

__all__ = [
    # Contract
    "CONTRACT_VERSION",
    "AccessSnapshot",
    "Envelope",
    "EnvelopeError",
    "SyncOrigin",
    "Visibility",
    "compute_content_hash",
    "entity_stable_id",
    "onyx_publish_id",
    "source_document_id",
    "validate_envelope",
    # Client
    "IngestResult",
    "OnyxClient",
    "OnyxClientError",
    "PushStatus",
    # Mapper
    "MapResult",
    "map_entity",
    # Sync state
    "PushState",
    "SyncStateStore",
    # Exporter
    "OnyxPushExporter",
    "PushOutcome",
    # Checkpoint
    "Checkpoint",
    "CheckpointStore",
    # Export Worker (Onyx → Mnemosyne)
    "BatchResult",
    "ExportWorker",
    "ProcessResult",
    # Permissions (Phase 4)
    "Provenance",
    "can_access",
    "classification_rank",
    "enrich_results_with_provenance",
    "extract_provenance",
    "filter_by_classification",
    "requires_review",
]
