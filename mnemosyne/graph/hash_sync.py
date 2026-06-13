"""
SPEC-HEADROOM-001 content-hash change detection (REQ-006, REQ-007).

Provides:
- ``compute_content_hash``: SHA-256 over the canonical extracted source content.
- ``should_skip``: predicate consumed by the update path's opt-in skip fast-path.

Hash input semantics (plan-phase decision R3):
    The hash is computed over the EXTRACTED SOURCE CONTENT that feeds the entity
    -- i.e. the text blob passed to ``update_entity(..., source_content=...)`` --
    NOT the raw bytes of the source file. A whitespace-only edit of the source
    file that leaves the extracted content unchanged therefore does not force a
    re-write. This keeps re-extraction cheap when models change cosmetics but
    not semantics.
"""

import hashlib


def compute_content_hash(source_content: str) -> str:
    """Return the SHA-256 hex digest of ``source_content`` (canonical UTF-8).

    Args:
        source_content: The extracted text that feeds the entity. Must be the
            same canonical form on every re-extraction for equality to hold.

    Returns:
        Lowercase 64-char hex digest.
    """
    return hashlib.sha256(source_content.encode("utf-8")).hexdigest()


def should_skip(stored_hash, new_hash: str) -> bool:
    """Return True iff an update should be skipped because content is unchanged.

    Args:
        stored_hash: The ``content_hash`` currently persisted on the entity
            (may be ``None`` for entities created before this column existed).
        new_hash: The freshly computed hash for the incoming source content.

    Returns:
        True only when both hashes are non-None and strictly equal. A ``None``
        stored hash means the entity has never been hashed -> never skip (the
        first hash must be persisted).
    """
    if stored_hash is None:
        return False
    return stored_hash == new_hash
