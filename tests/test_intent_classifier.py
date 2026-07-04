"""
Tests for intent classifier.
"""

import pytest

from mnemosyne.retrieval.intent import IntentClassifier, Intent


class TestIntentClassifier:
    """Tests for query intent classification."""

    def test_classify_temporal(self):
        """Should detect temporal intent."""
        classifier = IntentClassifier()

        queries = [
            "Q4 2024 earnings",
            "meetings from last week",
            "events in January 2025",
            "yesterday's standup",
        ]

        for query in queries:
            intent = classifier.classify(query)
            assert intent == "temporal", f"Query '{query}' classified as {intent}"

    def test_classify_event(self):
        """Should detect event/transaction intent."""
        classifier = IntentClassifier()

        queries = [
            "Tesla investment round",
            "latest merger",
            "hiring process",
            "product launch",
        ]

        for query in queries:
            intent = classifier.classify(query)
            assert intent == "event", f"Query '{query}' classified as {intent}"

    def test_classify_entity(self):
        """Should detect named entity intent."""
        classifier = IntentClassifier()

        queries = [
            "Elon Musk",
            "Sam Altman",
            "Tesla Inc",
        ]

        for query in queries:
            intent = classifier.classify(query)
            assert intent == "entity", f"Query '{query}' classified as {intent}"

    def test_classify_general(self):
        """Should default to general intent."""
        classifier = IntentClassifier()

        queries = [
            "how to implement caching",
            "best practices for testing",
            "python async patterns",
        ]

        for query in queries:
            intent = classifier.classify(query)
            assert intent == "general", f"Query '{query}' classified as {intent}"

    def test_classify_with_metadata_temporal(self):
        """Should extract temporal expressions."""
        classifier = IntentClassifier()

        result = classifier.classify_with_metadata("Q4 2024 earnings")

        assert isinstance(result, Intent)
        assert result.name == "temporal"
        assert "temporal_expressions" in result.metadata
        assert len(result.metadata["temporal_expressions"]) > 0

    def test_classify_with_metadata_event(self):
        """Should extract event keywords."""
        classifier = IntentClassifier()

        result = classifier.classify_with_metadata("Tesla investment round")

        assert isinstance(result, Intent)
        assert result.name == "event"
        assert "event_type" in result.metadata
        assert "matched_keywords" in result.metadata

    def test_classify_with_metadata_entity(self):
        """Should extract detected entities."""
        classifier = IntentClassifier()

        result = classifier.classify_with_metadata("Elon Musk")

        assert isinstance(result, Intent)
        assert result.name == "entity"
        assert "detected_entities" in result.metadata

    def test_confidence_value(self):
        """Should return confidence score."""
        classifier = IntentClassifier()

        result = classifier.classify_with_metadata("test query")

        assert 0 <= result.confidence <= 1

    def test_temporal_patterns_exist(self):
        """Temporal regex patterns should be defined."""
        classifier = IntentClassifier()

        assert len(classifier.TEMPORAL_PATTERNS) > 0

    def test_event_keywords_exist(self):
        """Event keyword groups should be defined."""
        classifier = IntentClassifier()

        assert len(classifier.EVENT_KEYWORDS) > 0
        for event_type, keywords in classifier.EVENT_KEYWORDS.items():
            assert len(keywords) > 0

    def test_get_temporal_expressions(self):
        """Should extract temporal expressions from query."""
        classifier = IntentClassifier()

        expressions = classifier.get_temporal_expressions("Q4 2024 earnings")

        assert len(expressions) > 0

    def test_get_event_keywords(self):
        """Should extract event keywords from query."""
        classifier = IntentClassifier()

        keywords = classifier.get_event_keywords("Tesla investment round")

        assert len(keywords) > 0
        assert "invest" in keywords or "round" in keywords

    def test_empty_query(self):
        """Should handle empty query."""
        classifier = IntentClassifier()

        intent = classifier.classify("")
        assert intent == "general"

    def test_query_with_whitespace(self):
        """Should handle whitespace-only query."""
        classifier = IntentClassifier()

        intent = classifier.classify("   ")
        assert intent == "general"

    def test_mixed_case_query(self):
        """Should be case-insensitive."""
        classifier = IntentClassifier()

        intent_lower = classifier.classify("tesla investment")
        intent_upper = classifier.classify("TESLA INVESTMENT")
        intent_mixed = classifier.classify("Tesla Investment")

        assert intent_lower == intent_upper == intent_mixed

    def test_looks_like_name_single_word(self):
        """Should detect single capitalized word as name."""
        classifier = IntentClassifier()

        assert classifier._looks_like_name("Tesla") is True
        assert classifier._looks_like_name("tesla") is False

    def test_looks_like_name_multiple_words(self):
        """Should detect capitalized phrase as name."""
        classifier = IntentClassifier()

        assert classifier._looks_like_name("Elon Musk") is True
        assert classifier._looks_like_name("elon musk") is False

    def test_looks_like_name_mixed_case(self):
        """Should detect mixed capitalized words."""
        classifier = IntentClassifier()

        # 50% capitalized threshold
        assert classifier._looks_like_name("Elon musk") is True  # 1/2 capitalized
        assert classifier._looks_like_name("elon Musk") is True  # 1/2 capitalized
