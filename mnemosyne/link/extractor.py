"""
Link extraction from markdown content.

Implements zero-LLM link extraction using regex patterns.
"""

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class LinkExtractor:
    """Extract entity references from markdown."""

    # Patterns for different link syntaxes
    PATTERNS = [
        # [text](path) - Standard markdown link
        r"\[([^\]]+)\]\(([^)]+)\)",
        # [[path|label]] - Wiki link with label (must come before [[path]])
        r"\[\[([^\]|]+)\|([^\]]+)\]\]",
        # [[path]] - Wiki link (no | allowed)
        r"\[\[([^\]|]+)\]\]",
    ]

    # Context patterns for type inference
    # More flexible patterns that match keywords even if links follow
    TYPE_PATTERNS = {
        "works_at": r"(?:works? at|employed by|joining)",
        "attended": r"(?:attended|met with|joined)",
        "authored": r"(?:authored|wrote|created)",
        "knows": r"(?:knows|connected to|friend of)",
        "founded": r"(?:founded|co-founded|started)",
    }

    def __init__(self):
        """Compile regex patterns."""
        self.link_patterns = [re.compile(p) for p in self.PATTERNS]
        self.type_patterns = {
            name: re.compile(pattern) for name, pattern in self.TYPE_PATTERNS.items()
        }

    def extract_links(
        self, markdown: str
    ) -> List[Tuple[str, str, Optional[str]]]:
        """Extract all entity references from markdown.

        Args:
            markdown: Markdown content to parse.

        Returns:
            [(link_text, target_path, context), ...]
            context is the surrounding sentence or None.
        """
        links = []

        for pattern in self.link_patterns:
            for match in pattern.finditer(markdown):
                groups = match.groups()

                # Handle different patterns based on group count
                if len(groups) == 2:
                    # Check which pattern based on content
                    if pattern.pattern.startswith(r"\[\["):
                        # [[path|label]] format - groups are (path, label)
                        target, link_text = groups
                    else:
                        # [text](path) format - groups are (text, path)
                        link_text, target = groups
                else:
                    # [[path]] format - single group
                    target = groups[0]
                    link_text = target

                # Get context (sentence containing the link)
                context = self._get_context(markdown, match.start())

                links.append((link_text, target, context))

        return links

    def _get_context(self, text: str, pos: int) -> Optional[str]:
        """Get surrounding sentence as context.

        Args:
            text: Full text.
            pos: Position of the link.

        Returns:
            Context sentence or None.
        """
        # Find sentence boundaries
        start = pos
        while start > 0 and text[start - 1] not in ".!?":
            start -= 1

        end = pos
        while end < len(text) and text[end] not in ".!?":
            end += 1

        if end < len(text):
            end += 1  # Include the period

        context = text[start:end].strip()
        return context if context else None

    def infer_link_type(
        self,
        source_type: Optional[str],
        target_path: str,
        context: Optional[str],
    ) -> Optional[str]:
        """Infer link type from context.

        Args:
            source_type: Type of the source entity.
            target_path: Path of the target entity.
            context: Surrounding context text.

        Returns:
            Inferred link type or None.
        """
        if not context:
            return None

        context_lower = context.lower()

        # Check type patterns
        for link_type, pattern in self.type_patterns.items():
            match = pattern.search(context_lower)
            if match:
                return link_type

        # Fallback: use generic 'mentions' for unknown contexts
        return "mentions"

    def extract_and_infer(
        self,
        markdown: str,
        source_type: Optional[str] = None,
    ) -> List[Tuple[str, str, Optional[str]]]:
        """Extract links and infer types in one pass.

        Args:
            markdown: Markdown content to parse.
            source_type: Type of the source entity (for better inference).

        Returns:
            [(link_text, target_path, inferred_type), ...]
        """
        raw_links = self.extract_links(markdown)

        result = []
        for link_text, target_path, context in raw_links:
            inferred_type = self.infer_link_type(source_type, target_path, context)
            result.append((link_text, target_path, inferred_type))

        return result

    def count_links(self, markdown: str) -> int:
        """Count total links in markdown.

        Args:
            markdown: Markdown content.

        Returns:
            Number of links found.
        """
        count = 0
        for pattern in self.link_patterns:
            count += len(pattern.findall(markdown))
        return count

    def has_links(self, markdown: str) -> bool:
        """Check if markdown contains any links.

        Args:
            markdown: Markdown content.

        Returns:
            True if any links found.
        """
        for pattern in self.link_patterns:
            if pattern.search(markdown):
                return True
        return False
