"""
SynthesisExtractor abstract base class and NoOpSynthesisExtractor (SPEC-PIPE-001 REQ-008).

Provides the contract for optional LLM-based synthesis extraction (Layer 3).
The NoOpSynthesisExtractor is the default and always returns empty results.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class SynthesisExtractor(ABC):
    """Abstract base class for LLM-based synthesis extraction.

    Implementations should override ``is_available`` and ``extract``.
    When ``is_available`` returns ``False``, the pipeline skips this layer.
    """

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the synthesis extractor is ready to use."""
        ...

    @abstractmethod
    def extract(
        self,
        text: str,
        existing_entities: List[Dict[str, Any]],
        domain: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Perform LLM synthesis extraction.

        Parameters
        ----------
        text:
            Raw source text.
        existing_entities:
            Entities extracted by previous layers.
        domain:
            Extraction domain (``coding``, ``daily``, ``legal``).
        scope_id:
            Optional scope identifier.
        source_channel:
            Optional source channel.

        Returns
        -------
        Dict with keys ``entities``, ``relations``, ``token_cost``.
        """
        ...


class NoOpSynthesisExtractor(SynthesisExtractor):
    """Default no-op implementation.  Always reports unavailable and returns empty."""

    @property
    def is_available(self) -> bool:
        return False

    def extract(
        self,
        text: str,
        existing_entities: List[Dict[str, Any]],
        domain: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {"entities": [], "relations": [], "token_cost": 0}
