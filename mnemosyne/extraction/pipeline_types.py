"""
Data models for the extraction pipeline (SPEC-PIPE-001).

Provides ExtractionResult, ExtractionError, LayerStats, ExtractionReport
dataclasses and the content_hash utility for incremental tracking.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def content_hash(data: bytes) -> str:
    """Return the first 16 hex characters of the SHA-256 digest of *data*.

    Used by IncrementalTracker to detect file-content changes.
    """
    return hashlib.sha256(data).hexdigest()[:16]


@dataclass
class ExtractionError:
    """Per-file extraction error record."""

    file_path: str
    error_type: str
    error_message: str
    layer: str
    traceback: Optional[str] = None


@dataclass
class LayerStats:
    """Per-layer extraction statistics."""

    entities_extracted: int = 0
    relations_extracted: int = 0
    files_processed: int = 0
    files_failed: int = 0
    estimated_tokens: int = 0


@dataclass
class ExtractionResult:
    """Single file/text extraction result."""

    source: str
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[ExtractionError] = field(default_factory=list)
    layers_used: List[str] = field(default_factory=list)
    estimated_tokens: int = 0


@dataclass
class ExtractionReport:
    """Full pipeline extraction report."""

    # Basic info
    domain: str
    source: str
    started_at: str  # ISO-8601
    completed_at: str  # ISO-8601

    # File statistics
    files_discovered: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    files_failed: int = 0

    # Extraction statistics
    entities_extracted: int = 0
    entities_stored: int = 0
    relations_extracted: int = 0
    relations_stored: int = 0

    # Per-layer statistics
    layer_deterministic: LayerStats = field(default_factory=LayerStats)
    layer_semantic: LayerStats = field(default_factory=LayerStats)
    layer_synthesis: LayerStats = field(default_factory=LayerStats)

    # Error info
    errors: List[ExtractionError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Resource estimate
    estimated_tokens: int = 0

    # Scope info
    scope_id: Optional[str] = None
    source_channel: str = "pipeline"
