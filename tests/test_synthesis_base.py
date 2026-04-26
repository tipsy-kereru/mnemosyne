"""
Tests for SynthesisExtractor ABC and NoOpSynthesisExtractor (SPEC-PIPE-001 REQ-008).

Covers: abstract enforcement, NoOp defaults, is_available, extract return value.
"""

import pytest

from mnemosyne.extraction.synthesis.base import (
    NoOpSynthesisExtractor,
    SynthesisExtractor,
)


class TestSynthesisExtractorABC:
    """REQ-008: Abstract interface compliance."""

    def test_cannot_instantiate_abc_directly(self):
        """AC-008-4: Instantiating without implementing abstract methods raises TypeError."""
        with pytest.raises(TypeError):
            SynthesisExtractor()

    def test_incomplete_subclass_raises_typeerror(self):
        """Subclass missing abstract methods cannot be instantiated."""

        class IncompleteExtractor(SynthesisExtractor):
            pass

        with pytest.raises(TypeError):
            IncompleteExtractor()

    def test_complete_subclass_instantiates(self):
        """Subclass with all abstract methods implemented can be instantiated."""

        class CompleteExtractor(SynthesisExtractor):
            @property
            def is_available(self) -> bool:
                return True

            def extract(self, text, existing_entities, domain,
                        scope_id=None, source_channel=None):
                return {"entities": [], "relations": [], "token_cost": 0}

        ext = CompleteExtractor()
        assert ext.is_available is True


class TestNoOpSynthesisExtractor:
    """REQ-008: No-op default behaviour."""

    def test_is_available_returns_false(self):
        """AC-008-2: is_available is False by default."""
        ext = NoOpSynthesisExtractor()
        assert ext.is_available is False

    def test_extract_returns_empty_result(self):
        """AC-008-1: extract returns empty entities/relations and zero cost."""
        ext = NoOpSynthesisExtractor()
        result = ext.extract(
            text="some text",
            existing_entities=[{"type": "function", "name": "foo"}],
            domain="coding",
            scope_id="s1",
            source_channel="vscode",
        )
        assert result["entities"] == []
        assert result["relations"] == []
        assert result["token_cost"] == 0

    def test_extract_ignores_all_inputs(self):
        """NoOp never errors regardless of inputs."""
        ext = NoOpSynthesisExtractor()
        result = ext.extract(text="", existing_entities=[], domain="legal")
        assert result["entities"] == []

    def test_is_subclass_of_synthesis_extractor(self):
        ext = NoOpSynthesisExtractor()
        assert isinstance(ext, SynthesisExtractor)
