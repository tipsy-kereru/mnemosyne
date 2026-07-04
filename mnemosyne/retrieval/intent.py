"""
Query intent classifier for hybrid search.

Determines query type to guide strategy selection:
- entity: Named entity queries ("Elon Musk", "Tesla")
- temporal: Time-based queries ("Q4 2024", "last meeting")
- event: Event/transaction queries ("merger", "investment")
- general: General knowledge queries
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Intent:
    """Query intent classification."""
    name: str  # entity, temporal, event, general
    confidence: float  # 0.0 to 1.0
    metadata: dict  # Additional context (e.g., detected entities)


class IntentClassifier:
    """Zero-cost intent classifier using patterns and keywords."""

    # Temporal patterns
    TEMPORAL_PATTERNS = [
        r"\b(?:Q[1-4])\s*\d{4}\b",  # Q1 2024
        r"\b\d{4}\s*-\s*Q[1-4]\b",  # 2024-Q1
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
        r"\b(?:last|next|previous|this)\s+(?:week|month|quarter|year)\b",
        r"\b(?:yesterday|today|tomorrow)\b",
        r"\b\d{4}-\d{2}-\d{2}\b",  # ISO dates
        r"\b(?:in|during|before|after|since)\s+(?:the\s+)?\d{4}\b",
    ]

    # Event/transaction keywords
    EVENT_KEYWORDS = {
        "investment": ["invest", "funding", "round", "series", "venture"],
        "merger": ["merge", "acquisition", "acquire", "buy", "sell", "ipo"],
        "meeting": ["meet", "call", "conference", "summit", "standup"],
        "release": ["launch", "release", "deploy", "ship", "announce"],
        "hire": ["hire", "hiring", "join", "onboard", "recruit", "leave"],
    }

    # Named entity detection (capitalized phrases)
    ENTITY_PATTERN = r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b"

    def __init__(self):
        """Compile regex patterns."""
        self.temporal_regex = re.compile(
            "|".join(self.TEMPORAL_PATTERNS), re.IGNORECASE
        )
        self.entity_regex = re.compile(self.ENTITY_PATTERN)

    def classify(self, query: str) -> str:
        """Classify query intent.

        Returns: One of 'entity', 'temporal', 'event', 'general'
        """
        query_lower = query.lower()

        # Check for temporal intent first (most specific)
        if self.temporal_regex.search(query):
            return "temporal"

        # Check for event keywords
        for event_type, keywords in self.EVENT_KEYWORDS.items():
            if any(keyword in query_lower for keyword in keywords):
                return "event"

        # Check for named entities (multiple capitalized words)
        entities = self.entity_regex.findall(query)
        if len(entities) >= 1:
            # Could be entity or general - prefer entity if looks like name
            if self._looks_like_name(query):
                return "entity"

        return "general"

    def _looks_like_name(self, query: str) -> bool:
        """Check if query looks like a named entity."""
        # Single capitalized word or multiple
        words = query.strip().split()
        if len(words) == 1:
            # Single capitalized word likely entity
            return words[0][0].isupper()

        # Multiple capitalized words
        capitalized = sum(1 for w in words if w and w[0].isupper())
        return capitalized >= len(words) * 0.5

    def classify_with_metadata(self, query: str) -> Intent:
        """Classify with detailed metadata."""
        name = self.classify(query)

        metadata = {"original_query": query}

        if name == "temporal":
            matches = self.temporal_regex.findall(query)
            metadata["temporal_expressions"] = matches

        elif name == "event":
            for event_type, keywords in self.EVENT_KEYWORDS.items():
                matched = [kw for kw in keywords if kw in query.lower()]
                if matched:
                    metadata["event_type"] = event_type
                    metadata["matched_keywords"] = matched
                    break

        elif name == "entity":
            entities = self.entity_regex.findall(query)
            metadata["detected_entities"] = entities

        return Intent(name=name, confidence=0.8, metadata=metadata)

    def get_temporal_expressions(self, query: str) -> List[str]:
        """Extract temporal expressions from query."""
        return self.temporal_regex.findall(query)

    def get_event_keywords(self, query: str) -> List[str]:
        """Extract event-related keywords from query."""
        query_lower = query.lower()
        found = []
        for keywords in self.EVENT_KEYWORDS.values():
            for kw in keywords:
                if kw in query_lower and kw not in found:
                    found.append(kw)
        return found
