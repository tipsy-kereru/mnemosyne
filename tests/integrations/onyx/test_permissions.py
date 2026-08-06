"""Tests for classification filtering, provenance citation, and
memory write gating (Phase 4 §6).

Permission tests from §8:
- Different scope_id search isolation (tested via existing KG scope tests)
- Classification clearance filtering
- Default deny on unknown classification
- Provenance fields in citations
- Memory write gating for non-auto-writable types
"""

from __future__ import annotations

from mnemosyne.integrations.onyx.permissions import (
    CLASSIFICATION_ORDER,
    DEFAULT_CLASSIFICATION,
    Provenance,
    REVIEW_REQUIRED_TYPES,
    can_access,
    classification_rank,
    enrich_results_with_provenance,
    extract_provenance,
    filter_by_classification,
    requires_review,
)


class TestClassificationRank:
    def test_order_is_most_to_least_restrictive(self):
        assert CLASSIFICATION_ORDER[0] == "private"
        assert CLASSIFICATION_ORDER[-1] == "public"

    def test_rank_values(self):
        assert classification_rank("private") == 0
        assert classification_rank("confidential") == 1
        assert classification_rank("internal") == 2
        assert classification_rank("public") == 3

    def test_unknown_defaults_to_most_restrictive(self):
        assert classification_rank("top-secret") == 0
        assert classification_rank("") == 0


class TestCanAccess:
    def test_public_visible_to_all(self):
        for level in CLASSIFICATION_ORDER:
            assert can_access("public", level) is True

    def test_private_visible_only_to_private_clearance(self):
        assert can_access("private", "private") is True
        assert can_access("private", "internal") is False
        assert can_access("private", "public") is False

    def test_internal_visible_to_internal_and_higher_clearance(self):
        """Internal docs need internal+ clearance. Public-only callers denied."""
        assert can_access("internal", "internal") is True
        assert can_access("internal", "confidential") is True   # higher clearance
        assert can_access("internal", "private") is True         # highest clearance
        assert can_access("internal", "public") is False         # insufficient clearance

    def test_confidential_visible_to_confidential_and_higher_clearance(self):
        """Confidential docs need confidential+ clearance."""
        assert can_access("confidential", "confidential") is True
        assert can_access("confidential", "private") is True      # highest clearance
        assert can_access("confidential", "internal") is False    # insufficient
        assert can_access("confidential", "public") is False      # insufficient


class TestFilterByClassification:
    def _entity(self, classification: str | None) -> dict:
        props = {}
        if classification is not None:
            props["classification"] = classification
        return {"id": "e1", "properties": props}

    def test_filters_out_above_clearance(self):
        entities = [
            self._entity("public"),
            self._entity("internal"),
            self._entity("confidential"),
            self._entity("private"),
        ]
        filtered = filter_by_classification(entities, "internal")
        classifications = [e["properties"]["classification"] for e in filtered]
        assert "public" in classifications
        assert "internal" in classifications
        assert "confidential" not in classifications
        assert "private" not in classifications

    def test_unknown_classification_defaults_to_private(self):
        """§4: default deny on unknown classification."""
        entities = [self._entity(None)]  # no classification key
        filtered = filter_by_classification(entities, "internal")
        assert len(filtered) == 0  # denied because unknown = private

    def test_unknown_classification_visible_to_private_clearance(self):
        entities = [self._entity(None)]
        filtered = filter_by_classification(entities, "private")
        assert len(filtered) == 1  # allowed at private clearance


class TestProvenance:
    def test_extract_from_flat_properties(self):
        props = {
            "external_uri": "https://github.com/org/repo/issues/1",
            "external_revision": "rev-abc",
            "captured_at": "2026-08-02T10:00:00Z",
            "source_channel": "github",
            "scope_id": "client-a",
            "classification": "internal",
        }
        prov = extract_provenance(props)
        assert prov.source_uri == "https://github.com/org/repo/issues/1"
        assert prov.external_revision == "rev-abc"
        assert prov.captured_at == "2026-08-02T10:00:00Z"
        assert prov.has_provenance is True

    def test_extract_handles_missing_fields(self):
        prov = extract_provenance({})
        assert prov.source_uri == ""
        assert prov.has_provenance is False
        assert prov.classification == DEFAULT_CLASSIFICATION

    def test_extract_handles_source_uri_alias(self):
        """Both 'external_uri' and 'source_uri' are recognized."""
        prov = extract_provenance({"source_uri": "https://example.com"})
        assert prov.source_uri == "https://example.com"

    def test_enrich_adds_provenance_to_results(self):
        results = [
            {"id": "e1", "properties": {"external_uri": "https://a.com"}},
            {"id": "e2", "properties": {}},
        ]
        enriched = enrich_results_with_provenance(results)
        assert "provenance" in enriched[0]
        assert enriched[0]["provenance"]["source_uri"] == "https://a.com"
        assert enriched[1]["provenance"].get("source_uri", "") == ""

    def test_provenance_to_dict_omits_empty(self):
        prov = Provenance(source_uri="https://a.com")
        d = prov.to_dict()
        assert "source_uri" in d
        assert "external_revision" not in d  # empty values omitted


class TestMemoryWriteGating:
    def test_curated_types_require_review_by_default(self):
        assert requires_review("requirement") is True
        assert requires_review("decision") is True
        assert requires_review("risk") is True
        assert requires_review("conflict") is True
        assert requires_review("blocker") is True
        assert requires_review("release") is True

    def test_observational_types_bypass_review(self):
        """Common types (person, task, function, note) are auto-writable."""
        for t in ("person", "task", "function", "note", "event",
                   "reference", "bug", "feature", "class", "module"):
            assert requires_review(t) is False, f"{t} should be auto-writable"

    def test_explicit_auto_write_bypasses_review(self):
        """Explicit opt-in flag overrides review requirement."""
        assert requires_review("requirement", auto_write=True) is False
        assert requires_review("decision", auto_write=True) is False


def test_unknown_caller_clearance_denies_access():
    assert can_access("private", "") is False
    assert can_access("private", "PUBLIC") is False
    assert can_access("confidential", "guest") is False
    assert can_access("public", None) is False


def test_t58_missing_or_unknown_clearance_is_always_denied():
    assert can_access("x", None) is False
    assert can_access("x", "") is False
    assert can_access("x", "guest") is False
