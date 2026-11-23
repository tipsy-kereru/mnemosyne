"""Read-only, exact-scope evidence search (see :mod:`mnemosyne.evidence.search`)."""

from mnemosyne.evidence.search import (
    CONTRACT,
    FRESHNESS_CONTRACT,
    evidence_freshness,
    search_evidence,
)

__all__ = ["CONTRACT", "FRESHNESS_CONTRACT", "evidence_freshness", "search_evidence"]
