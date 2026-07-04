"""
Auto-link system for Mnemosyne.

Provides automatic entity reference extraction and link creation.
"""

from mnemosyne.link.extractor import LinkExtractor
from mnemosyne.link.auto_linker import AutoLinker

__all__ = [
    "LinkExtractor",
    "AutoLinker",
]
