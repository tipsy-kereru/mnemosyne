"""
SPEC-HEADROOM-001 FTS5 ranked search (REQ-001, REQ-002, REQ-00ROOM, REQ-003).

Provides an idempotent schema helper that creates the ``entity_fts`` FTS5
external-content virtual table over ``entities`` plus the three sync triggers
(insert / update / delete), and backfills the FTS index from any pre-existing
``entities`` rows on first creation. Also provides the ranked search helper
used by ``KnowledgeGraph._query_search``.

All schema DDL here is additive and idempotent: each statement is guarded by
an existence check against ``sqlite_master``, matching the existing
``_init_session_schema`` convention in ``knowledge_graph.py``.
"""

import logging
import re
import sqlite3
import unicodedata
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def normalize_search_tokens(term: str) -> List[str]:
    """Generate normalized search variants for Korean alias matching.

    Expands a search term into variants that match different representations:
    - "내부 처리" -> ["내부 처리", "내부처리", "내부", "처리"]
    - "내부-처리" -> ["내부-처리", "내부처리", "내부", "처리"]

    This handles Korean text that may be written with or without spaces/hyphens.

    Args:
        term: The raw search term from user input.

    Returns:
        List of normalized variants, ordered by specificity (exact > compact > split).
    """
    if not term:
        return []

    # NFKC normalization for Korean compatibility
    normalized = unicodedata.normalize("NFKC", term).strip()

    variants = {
        normalized,  # exact: "내부 처리"
    }

    # Compact: remove spaces, hyphens, slashes, underscores -> "내부처리"
    compact = re.sub(r"[\s\-_/]+", "", normalized)
    if compact:
        variants.add(compact)

    # Split: individual tokens -> ["내부", "처리"]
    split_tokens = [
        token for token in re.split(r"[\s\-_/]+", normalized)
        if token
    ]
    variants.update(split_tokens)

    # Return ordered by specificity (exact > compact > split)
    result = []
    if normalized:
        result.append(normalized)
    if compact and compact != normalized:
        result.append(compact)
    for token in split_tokens:
        if token not in result:
            result.append(token)

    return result


def fts5_compile_available(conn: sqlite3.Connection) -> bool:
    """True iff the stdlib sqlite3 was compiled with FTS5 support."""
    try:
        opts = [r[0] for r in conn.execute("PRAGMA compile_options")]
    except sqlite3.Error:
        return False
    return "ENABLE_FTS5" in opts


def entity_fts_exists(conn: sqlite3.Connection) -> bool:
    """True iff the ``entity_fts`` virtual table currently exists."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='entity_fts'"
    ).fetchone()
    return row is not None


def _trigger_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
    ).fetchone()
    return row is not None


def create_entity_fts(conn: sqlite3.Connection) -> bool:
    """Create the entity_fts virtual table, sync triggers, and backfill.

    Idempotent: safe to call on every schema init. Returns True if the FTS
    table is available after the call (created or pre-existing), False if the
    runtime sqlite3 lacks FTS5 support (REQ-004 graceful degradation).
    """
    if not fts5_compile_available(conn):
        logger.warning(
            "FTS5 not enabled in this sqlite3 build; entity search will use LIKE fallback"
        )
        return False

    if entity_fts_exists(conn):
        # Ensure triggers exist even if the table was created out-of-band
        _create_triggers(conn)
        conn.commit()
        return True

    cursor = conn.cursor()
    # REQ-001: FTS5 external-content table over entities (default unicode61 tokenizer).
    cursor.execute(
        """CREATE VIRTUAL TABLE entity_fts USING fts5(
            name, type, properties,
            content='entities', content_rowid='rowid'
        )"""
    )

    _create_triggers(conn)

    # REQ-00ROOM: first-time backfill from pre-existing entities rows.
    cursor.execute("INSERT INTO entity_fts(rowid, name, type, properties) "
                   "SELECT rowid, name, type, properties FROM entities")

    conn.commit()
    logger.info("entity_fts created and backfilled from %d existing entities",
                _count(conn, "entities"))
    return True


def _create_triggers(conn: sqlite3.Connection) -> None:
    """Create the AFTER INSERT/UPDATE/DELETE sync triggers, idempotently.

    REQ-002: the AFTER UPDATE trigger issues a DELETE-then-INSERT on the FTS
    table because FTS5 external-content tables do not support in-place UPDATE.
    """
    cursor = conn.cursor()

    if not _trigger_exists(conn, "entity_ai"):
        cursor.execute(
            """CREATE TRIGGER entity_ai AFTER INSERT ON entities BEGIN
                INSERT INTO entity_fts(rowid, name, type, properties)
                VALUES (new.rowid, new.name, new.type, new.properties);
            END"""
        )
    if not _trigger_exists(conn, "entity_ad"):
        cursor.execute(
            """CREATE TRIGGER entity_ad AFTER DELETE ON entities BEGIN
                INSERT INTO entity_fts(entity_fts, rowid, name, type, properties)
                VALUES ('delete', old.rowid, old.name, old.type, old.properties);
            END"""
        )
    if not _trigger_exists(conn, "entity_au"):
        cursor.execute(
            """CREATE TRIGGER entity_au AFTER UPDATE ON entities BEGIN
                INSERT INTO entity_fts(entity_fts, rowid, name, type, properties)
                VALUES ('delete', old.rowid, old.name, old.type, old.properties);
                INSERT INTO entity_fts(rowid, name, type, properties)
                VALUES (new.rowid, new.name, new.type, new.properties);
            END"""
        )


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def fts_search_ready(conn: sqlite3.Connection) -> bool:
    """True iff FTS5 is available AND entity_fts is present and queryable."""
    if not fts5_compile_available(conn):
        return False
    return entity_fts_exists(conn)


def build_match_term(term: str) -> str:
    """Translate a user search term into a safe FTS5 MATCH expression.

    User search terms are treated as plain text, not FTS5 syntax. This prevents
    characters like '-' from being interpreted as FTS5 operators (e.g.,
    "내부-처리" causing "no such column: 처리" errors).

    Strategy: split the term into tokens and match each with prefix search.
    This enables bidirectional matching:
    - "내부처리" -> "내부"* OR "처리"* matches "내부 처리"
    - "내부 처리" -> "내부"* OR "처리"* matches "내부처리"

    Terms that look like explicit FTS5 queries (already quoted, has AND/OR, etc.)
    are passed through unchanged.

    Args:
        term: Raw user search term.

    Returns:
        FTS5 MATCH expression with OR logic for each token.
    """
    if not term:
        return ""

    # Detect explicit FTS5 syntax (user knows what they're doing)
    # Look for quoted phrases, explicit AND/OR, parenthetical groups
    if '"' in term or (' AND ' in term.upper()) or (' OR ' in term.upper()) or term.startswith('('):
        return term

    # Generate normalized variants and get split tokens
    tokens = normalize_search_tokens(term)
    if not tokens:
        return ""

    # Use individual tokens for prefix matching (not phrase search)
    # This enables "내부"* OR "처리"* to match both "내부 처리" and "내부처리"
    # Extract individual tokens from all variants (unique, non-empty)
    seen = set()
    individual_tokens = []
    for token in tokens:
        # Split each variant further by delimiters
        for part in re.split(r"[\s\-_/]+", token):
            if part and part not in seen:
                seen.add(part)
                individual_tokens.append(part)

    if not individual_tokens:
        return ""

    # Quote each token for phrase search and add prefix wildcard
    # Join with OR to match any token
    return " OR ".join(f'"{token}"*' for token in individual_tokens)


def ranked_search(
    conn: sqlite3.Connection,
    term: str,
    where_clauses: Optional[List[str]] = None,
    where_params: Optional[List[Any]] = None,
    limit: int = 100,
) -> List[sqlite3.Row]:
    """Run a bm25-ranked FTS5 search joined back to the entities table.

    ``where_clauses`` / ``where_params`` are scope/channel/time fragments
    already built against the ``e`` (entities) alias by the caller, so the
    FTS5 path composes transparently with the existing modifier machinery.

    Returns rows ordered by bm25 relevance (best match first).
    """
    where_clauses = where_clauses or []
    where_params = list(where_params or [])

    match_expr = build_match_term(term)
    clauses = ["entity_fts MATCH ?"]
    params: List[Any] = [match_expr]
    clauses.extend(where_clauses)
    params.extend(where_params)

    where_sql = " AND ".join(clauses)
    sql = (
        "SELECT e.id, e.type, e.name, e.properties, e.scope_id, e.source_channel "
        "FROM entity_fts JOIN entities e ON e.rowid = entity_fts.rowid "
        f"WHERE {where_sql} "
        "ORDER BY bm25(entity_fts) LIMIT ?"
    )
    params.append(limit)
    return conn.execute(sql, params).fetchall()
