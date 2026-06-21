"""SPEC-LONGDOC-001: PageIndex-style long-document tree indexing.

Public entry points:
    - ``LongDocIndexer`` (``tree_indexer.py``): splits + builds tree.
    - ``LongDocRetriever`` (``retriever.py``): FTS5 + entity-overlap scoring.
    - ``detect_longdoc`` (``detector.py``): REQ-LD-001 threshold check.
    - ``validate_longdoc_path`` (``security.py``): path-traversal guard.
"""

from mnemosyne.extraction.longdoc.detector import (
    LONGDOC_DEFAULT_PAGE_THRESHOLD,
    LONGDOC_DEFAULT_TOKEN_THRESHOLD,
    detect_longdoc,
)
from mnemosyne.extraction.longdoc.security import (
    LongDocPathError,
    validate_longdoc_path,
)
from mnemosyne.extraction.longdoc.tree_indexer import (
    LongDocIndexer,
    TreeNode,
)
from mnemosyne.extraction.longdoc.retriever import LongDocRetriever

__all__ = [
    "LONGDOC_DEFAULT_PAGE_THRESHOLD",
    "LONGDOC_DEFAULT_TOKEN_THRESHOLD",
    "detect_longdoc",
    "LongDocIndexer",
    "LongDocPathError",
    "LongDocRetriever",
    "TreeNode",
    "validate_longdoc_path",
]
