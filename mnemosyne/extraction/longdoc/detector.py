"""SPEC-LONGDOC-001 REQ-LD-001: long-document detector.

A document is "long" when its estimated token count exceeds
``MNEMOSYNE_LONGDOC_THRESHOLD`` (default 10000) OR its page count exceeds
``MNEMOSYNE_LONGDOC_PAGE_THRESHOLD`` (default 20). Both thresholds are
configurable via environment variables.
"""

from __future__ import annotations

import os

# REQ-LD-001: default thresholds. Overridable via env for tests / tuning.
LONGDOC_DEFAULT_TOKEN_THRESHOLD = 10000
LONGDOC_DEFAULT_PAGE_THRESHOLD = 20


def _env_int(name: str, default: int) -> int:
    """Read an integer env var, falling back to *default* on any parse error."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return default
    return val if val > 0 else default


def longdoc_token_threshold() -> int:
    """Active token threshold (env: ``MNEMOSYNE_LONGDOC_THRESHOLD``)."""
    return _env_int("MNEMOSYNE_LONGDOC_THRESHOLD", LONGDOC_DEFAULT_TOKEN_THRESHOLD)


def longdoc_page_threshold() -> int:
    """Active page-count threshold (env: ``MNEMOSYNE_LONGDOC_PAGE_THRESHOLD``)."""
    return _env_int(
        "MNEMOSYNE_LONGDOC_PAGE_THRESHOLD", LONGDOC_DEFAULT_PAGE_THRESHOLD
    )


def detect_longdoc(estimated_tokens: int, page_count: int = 0) -> bool:
    """True iff *estimated_tokens* or *page_count* cross the long-doc threshold.

    REQ-LD-001. ``page_count`` defaults to 0 (unknown); only the token
    threshold then applies.
    """
    if estimated_tokens > longdoc_token_threshold():
        return True
    if page_count and page_count > longdoc_page_threshold():
        return True
    return False
