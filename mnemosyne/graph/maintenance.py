"""
SPEC-HEADROOM-001 broken-link / stale-entity detection (REQ-008).

Surfaces two classes of broken references without ever mutating anything:

1. Wiki-style ``[[entity:type:name]]`` links (found in entity properties and in
   ``*.md`` files under an optional wiki root) whose target entity does not
   exist in the current graph.
2. ``source_file`` references stored on entities that no longer resolve on the
   filesystem.

The detector reports warnings only. Remediation (rename, delete, re-point) is
a separate human-in-the-loop step -- this module never writes to the graph or
the filesystem.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Matches [[entity:type:name]] (and tolerates surrounding whitespace).
_ENTITY_LINK_RE = re.compile(r"\[\[entity:([a-zA-Z_]+):([^\]\[]+?)\]\]")

# Properties keys commonly holding source file references.
_SOURCE_FILE_KEYS = ("source_file", "source_path", "file")


@dataclass
class BrokenLink:
    """A single unresolved reference surfaced by the maintenance suite."""

    source: str
    target: str
    kind: str  # 'entity' or 'source_file'


def _resolve_entity_exists(kg, entity_type: str, entity_name: str) -> bool:
    """True iff an entity with (type, name) exists in the graph."""
    row = kg.conn.execute(
        "SELECT 1 FROM entities WHERE type = ? AND name = ? LIMIT 1",
        (entity_type, entity_name),
    ).fetchone()
    return row is not None


def _extract_entity_links(text: str):
    """Yield (full_link, type, name) tuples for every [[entity:...]] match."""
    if not text:
        return
    for match in _ENTITY_LINK_RE.finditer(text):
        yield match.group(0), match.group(1), match.group(2)


def _iter_entity_property_text(kg):
    """Yield (entity_id, text_blob) for every entity's serialized properties."""
    for row in kg.conn.execute("SELECT id, properties FROM entities").fetchall():
        yield row["id"], row["properties"] or "{}"


def _scan_entity_links(kg) -> List[BrokenLink]:
    """Find [[entity:...]] links in entity properties that point at absent entities."""
    broken: List[BrokenLink] = []
    for entity_id, properties_json in _iter_entity_property_text(kg):
        try:
            json.loads(properties_json)  # validate JSON parses before scanning
        except (json.JSONDecodeError, TypeError):
            continue
        # Scan both the serialized JSON blob and nested values so links inside
        # any property value are caught.
        blob = properties_json
        for _full, etype, ename in _extract_entity_links(blob):
            if not _resolve_entity_exists(kg, etype, ename.strip()):
                broken.append(
                    BrokenLink(
                        source=entity_id,
                        target=f"entity:{etype}:{ename.strip()}",
                        kind="entity",
                    )
                )
    return broken


def _scan_source_files(kg) -> List[BrokenLink]:
    """Find entities whose ``source_file`` no longer exists on disk."""
    broken: List[BrokenLink] = []
    for entity_id, properties_json in _iter_entity_property_text(kg):
        try:
            props = json.loads(properties_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(props, dict):
            continue
        for key in _SOURCE_FILE_KEYS:
            if key not in props:
                continue
            path = props[key]
            if not isinstance(path, str) or not path:
                continue
            if not os.path.exists(path):
                broken.append(
                    BrokenLink(source=entity_id, target=path, kind="source_file")
                )
    return broken


def _scan_wiki_markdown(kg, wiki_root: Path) -> List[BrokenLink]:
    """Scan ``*.md`` files under ``wiki_root`` for broken ``[[entity:...]]`` links."""
    broken: List[BrokenLink] = []
    if wiki_root is None:
        return broken
    wiki_root = Path(wiki_root)
    if not wiki_root.exists():
        return broken
    for md_path in wiki_root.rglob("*.md"):
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for _full, etype, ename in _extract_entity_links(text):
            if not _resolve_entity_exists(kg, etype, ename.strip()):
                broken.append(
                    BrokenLink(
                        source=str(md_path),
                        target=f"entity:{etype}:{ename.strip()}",
                        kind="entity",
                    )
                )
    return broken


def find_broken_links(kg, wiki_root: Optional[Path] = None) -> List[BrokenLink]:
    """Detect broken ``[[entity:...]]`` and ``source_file`` references.

    Args:
        kg: A ``KnowledgeGraph`` whose ``conn`` and ``entities`` table are
            inspected read-only.
        wiki_root: Optional directory of ``*.md`` files to scan in addition to
            entity properties.

    Returns:
        List of ``BrokenLink`` records. The detector performs NO writes -- it
        never deletes, renames, or re-points anything (REQ-008).
    """
    broken: List[BrokenLink] = []
    broken.extend(_scan_entity_links(kg))
    broken.extend(_scan_source_files(kg))
    if wiki_root is not None:
        broken.extend(_scan_wiki_markdown(kg, Path(wiki_root)))

    # Deduplicate identical (source, target, kind) reports so a link referenced
    # multiple times in one entity is surfaced once.
    seen = set()
    deduped: List[BrokenLink] = []
    for link in broken:
        key = (link.source, link.target, link.kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)

    for link in deduped:
        logger.warning(
            "Broken link: source=%s target=%s kind=%s", link.source, link.target, link.kind
        )
    return deduped
