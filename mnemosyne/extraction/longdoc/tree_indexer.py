"""SPEC-LONGDOC-001 REQ-LD-002 / REQ-LD-005 / REQ-LD-006: tree indexer.

``LongDocIndexer`` ingests a single long document (markdown or PDF),
splits it into sections (heading-based for markdown, page-boundary for PDF),
groups sections into a hierarchical tree (max depth 4, max fan-out 8),
generates a per-node summary (GLiNER2Extractor first, LLMBridge fallback,
NULL on failure), and persists the tree to ``document_trees`` / ``tree_nodes``
additively.

No ``DELETE`` is ever emitted. Re-indexing a ``source_hash`` with an existing
active tree flips the prior tree to ``status='superseded'`` with
``superseded_by=<new_tree_id>`` then inserts the new tree as ``active``
(REQ-LD-006).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

from mnemosyne.extraction.longdoc.security import (
    LongDocPathError,
    redact,
    validate_longdoc_path,
)
from mnemosyne.timestamps import utc_now_iso

logger = logging.getLogger(__name__)

# REQ-LD-002: structural caps. Shallow PageIndex-like trees.
MAX_DEPTH = 4
MAX_FANOUT = 8

# R-LD-002: warn (do not fail) when node count exceeds this.
NODE_WARN_THRESHOLD = 200

# R-LD-001 REVIEW-phase hardening: hard caps to bound memory and row growth.
MAX_LONGDOC_PAGES = 1000
MAX_LONGDOC_BYTES = 50 * 1024 * 1024  # 50 MiB
MAX_LONGDOC_NODES = 5000

# Heading regex for the markdown splitter. Matches 1-6 leading '#'.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

# Approximate tokens-per-word ratio (cheap estimate; matches heuristic used
# elsewhere in the codebase where 1 token ~ 0.75 word, so 4/3 words/token).
_WORDS_PER_TOKEN = 0.75


def _estimate_tokens(text: str) -> int:
    """Cheap token estimate: ~0.75 words per token."""
    if not text:
        return 0
    return max(1, int(len(text.split()) / _WORDS_PER_TOKEN))


# ---------------------------------------------------------------------------
# Splitters
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """A contiguous slice of the source document.

    ``title`` is used to derive the node ``path``; ``body`` is summarised;
    ``token_start`` / ``token_end`` are the inclusive token offsets into the
    whole-document token stream.
    """

    title: str
    body: str
    token_start: int
    token_end: int
    ordinal: int = 0
    level: int = 0


def split_markdown(text: str) -> List[Section]:
    """Split markdown *text* into ``Section`` chunks by ATX headings.

    Text before the first heading is emitted as a synthetic "Introduction"
    section (only when non-empty). Token offsets are cumulative across
    sections so a tree node's ``token_range`` reflects its position in the
    full document.
    """
    sections: List[Section] = []
    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        # No headings at all: treat the whole document as a single section.
        tokens = _estimate_tokens(text)
        return [Section(
            title="root",
            body=text,
            token_start=0,
            token_end=tokens,
            ordinal=0,
        )]

    token_cursor = 0
    ordinal = 0

    # Preamble before first heading (optional).
    preamble = text[: matches[0].start()].strip()
    if preamble:
        body = preamble
        t = _estimate_tokens(body)
        sections.append(Section(
            title="Introduction",
            body=body,
            token_start=token_cursor,
            token_end=token_cursor + t,
            ordinal=ordinal,
        ))
        token_cursor += t
        ordinal += 1

    for idx, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip() or f"section-{ordinal}"
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        # Body excludes the heading line itself.
        body = text[start:end].strip()
        t = _estimate_tokens(body)
        sections.append(Section(
            title=title,
            body=body,
            level=level,
            token_start=token_cursor,
            token_end=token_cursor + t,
            ordinal=ordinal,
        ))
        token_cursor += t
        ordinal += 1
    return sections


def split_pdf_pages(pdf_path: Path) -> List[Section]:
    """Split a PDF file into one ``Section`` per page (page-boundary splitter).

    Uses ``pymupdf`` (``import fitz``) as a *soft* runtime dependency: it is
    deliberately NOT listed in ``pyproject.toml``. When the library is absent
    we raise ``ImportError`` so the caller can surface an ``ExtractionError``
    and degrade gracefully (REQ-LD-008 + SPEC §6 soft-dep policy).
    """
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "pymupdf (fitz) is not installed; PDF long-doc parsing is "
            "disabled. Install pymupdf to enable PDF input."
        ) from exc

    doc = fitz.open(str(pdf_path))  # type: ignore[attr-defined]
    try:
        # R-LD-001 REVIEW-phase: reject >1000-page PDFs to bound memory.
        if len(doc) > MAX_LONGDOC_PAGES:
            raise LongDocPathError(
                f"PDF exceeds {MAX_LONGDOC_PAGES} page cap "
                f"(got {len(doc)} pages): {pdf_path}"
            )
        sections: List[Section] = []
        token_cursor = 0
        for i in range(len(doc)):
            page = doc.load_page(i)
            body = page.get_text("text") or ""
            t = _estimate_tokens(body)
            sections.append(Section(
                title=f"page-{i + 1}",
                body=body,
                token_start=token_cursor,
                token_end=token_cursor + t,
                ordinal=i,
            ))
            token_cursor += t
        return sections
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Tree builder
# ---------------------------------------------------------------------------


@dataclass
class TreeNode:
    """In-memory tree node prior to persistence.

    ``children`` is populated by the builder. ``entity_refs`` is the list of
    extracted entity IDs (or names if IDs unavailable) that fell inside the
    node's token range.
    """

    node_id: str
    parent_id: Optional[str]
    path: str
    depth: int
    token_start: int
    token_end: int
    ordinal: int
    summary: Optional[str] = None
    entity_refs: List[str] = field(default_factory=list)
    raw_excerpt: str = ""
    children: List["TreeNode"] = field(default_factory=list)


def _slugify(title: str, ordinal: int) -> str:
    """Produce a stable, path-safe slug from *title* (falls back to ordinal)."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = f"node-{ordinal}"
    return slug[:48]


def _build_tree(sections: List[Section]) -> List[TreeNode]:
    """Group *sections* into a tree capped at ``MAX_DEPTH`` / ``MAX_FANOUT``.

    Returns the list of root-level ``TreeNode`` objects. Nodes form a shallow
    hierarchy: when a parent would exceed ``MAX_FANOUT`` children, the
    overflow children are pushed one level down under a synthetic
    ``group-N`` bucket node. Depth is capped at ``MAX_DEPTH`` (4): once that
    is reached any further nesting flattens into the deepest level.
    """
    roots: List[TreeNode] = []
    if not sections:
        return roots

    # Single section: emit one root node.
    if len(sections) == 1:
        s = sections[0]
        return [TreeNode(
            node_id=str(uuid.uuid4()),
            parent_id=None,
            path=f"root/{_slugify(s.title, s.ordinal)}",
            depth=0,
            token_start=s.token_start,
            token_end=s.token_end,
            ordinal=s.ordinal,
            raw_excerpt=s.body[:512],
        )]

    # Otherwise: bucket sections into groups of MAX_FANOUT under a root node,
    # then recursively subdivide any group larger than MAX_FANOUT until depth
    # reaches MAX_DEPTH. This yields a PageIndex-like shallow fan-out tree.
    def emit_bucket(
        parent_path: str,
        parent_id: Optional[str],
        depth: int,
        bucket_sections: List[Section],
    ) -> List[TreeNode]:
        if not bucket_sections or depth > MAX_DEPTH:
            return []
        nodes: List[TreeNode] = []
        # Chunk at MAX_FANOUT. If still too big at this depth, each chunk
        # becomes a leaf when depth == MAX_DEPTH, else a recursive bucket.
        chunks: List[List[Section]] = [
            bucket_sections[i : i + MAX_FANOUT]
            for i in range(0, len(bucket_sections), MAX_FANOUT)
        ]
        for ci, chunk in enumerate(chunks):
            path = f"{parent_path}/group-{ci}" if parent_path else f"root/group-{ci}"
            if len(chunk) == 1 and (len(chunks) == 1 or depth == MAX_DEPTH):
                s = chunk[0]
                leaf_path = (
                    f"{parent_path}/{_slugify(s.title, s.ordinal)}"
                    if parent_path
                    else f"root/{_slugify(s.title, s.ordinal)}"
                )
                nodes.append(TreeNode(
                    node_id=str(uuid.uuid4()),
                    parent_id=parent_id,
                    path=leaf_path,
                    depth=depth,
                    token_start=s.token_start,
                    token_end=s.token_end,
                    ordinal=s.ordinal,
                    raw_excerpt=s.body[:512],
                ))
            elif depth == MAX_DEPTH:
                # Flatten chunk into leaves at the cap depth.
                for s in chunk:
                    leaf_path = f"{parent_path}/{_slugify(s.title, s.ordinal)}"
                    nodes.append(TreeNode(
                        node_id=str(uuid.uuid4()),
                        parent_id=parent_id,
                        path=leaf_path,
                        depth=depth,
                        token_start=s.token_start,
                        token_end=s.token_end,
                        ordinal=s.ordinal,
                        raw_excerpt=s.body[:512],
                    ))
            else:
                # Recurse: this chunk becomes an internal bucket node whose
                # children are further subdivisions.
                bucket_node = TreeNode(
                    node_id=str(uuid.uuid4()),
                    parent_id=parent_id,
                    path=path,
                    depth=depth,
                    token_start=chunk[0].token_start,
                    token_end=chunk[-1].token_end,
                    ordinal=ci,
                    raw_excerpt="",
                )
                children = emit_bucket(path, bucket_node.node_id, depth + 1, chunk)
                bucket_node.children = children
                nodes.append(bucket_node)
        return nodes

    roots = emit_bucket("", None, 0, sections)
    return roots


def _flatten(nodes: List[TreeNode]) -> List[TreeNode]:
    """Pre-order flatten of a tree node list (root nodes + descendants)."""
    out: List[TreeNode] = []
    stack: List[TreeNode] = list(nodes)
    while stack:
        n = stack.pop(0)
        out.append(n)
        stack = list(n.children) + stack
    return out


# ---------------------------------------------------------------------------
# Summariser
# ---------------------------------------------------------------------------


class _Summariser:
    """REQ-LD-005: GLiNER2-first, LLM-fallback, NULL-on-failure summary.

    Lazily constructed so the SLM is only loaded when actually needed. Each
    call returns ``(summary_or_None, entity_refs)``.
    """

    def __init__(self, entity_types: List[str], domain: str = "daily") -> None:
        self._entity_types = list(entity_types)
        self._domain = domain
        self._gliner: Any = None
        self._gliner_tried = False
        self._llm: Any = None
        self._llm_tried = False

    def _get_gliner(self) -> Any:
        if self._gliner_tried:
            return self._gliner
        self._gliner_tried = True
        try:
            from mnemosyne.extraction.semantic.slm_extractor import GLiNER2Extractor
            self._gliner = GLiNER2Extractor()
        except Exception as exc:  # pragma: no cover - import / load errors
            logger.warning("GLiNER2 unavailable for longdoc summary: %s", exc)
            self._gliner = None
        return self._gliner

    def _get_llm(self) -> Any:
        if self._llm_tried:
            return self._llm
        self._llm_tried = True
        try:
            from mnemosyne.ingest.llm_bridge import LLMBridge
            self._llm = LLMBridge()
        except Exception as exc:  # pragma: no cover - import errors
            logger.warning("LLMBridge unavailable for longdoc summary: %s", exc)
            self._llm = None
        return self._llm

    def summarise(self, body: str) -> Tuple[Optional[str], List[str]]:
        """Return (summary, entity_refs) for *body*.

        REQ-LD-005: GLiNER2 first (entities serve as summary keywords + refs);
        on ImportError or empty result fall back to LLMBridge.extract; on LLM
        failure return ``(None, [])`` and proceed in degraded mode.
        """
        if not body.strip():
            return None, []

        entity_refs: List[str] = []
        # SLM path.
        gliner = self._get_gliner()
        if gliner is not None:
            try:
                ents = gliner.extract(
                    body[:8000],
                    self._entity_types,
                    threshold=0.5,
                )
                for e in ents:
                    txt = getattr(e, "text", "") or str(getattr(e, "name", ""))
                    if txt and txt not in entity_refs:
                        entity_refs.append(txt)
            except Exception as exc:  # pragma: no cover - depends on runtime libs
                logger.debug("GLiNER2 extract failed for longdoc node: %s", exc)
                ents = []

            if entity_refs:
                # Compact keyword-style summary derived from extracted entities.
                summary = "; ".join(sorted(entity_refs))[:300]
                return summary, entity_refs

        # LLM fallback.
        llm = self._get_llm()
        if llm is not None:
            try:
                result = llm.extract(
                    body[:8000],
                    schema_hint=", ".join(self._entity_types),
                    domain=self._domain,
                )
                nodes = result.get("nodes", []) if isinstance(result, dict) else []
                labels = [
                    n.get("label") or n.get("id") or ""
                    for n in nodes
                    if isinstance(n, dict)
                ]
                labels = [lbl for lbl in labels if lbl]
                if labels:
                    entity_refs = labels
                    summary = "; ".join(labels)[:300]
                    return summary, entity_refs
            except Exception as exc:  # pragma: no cover - depends on runtime libs
                logger.debug("LLM extract failed for longdoc node: %s", exc)

        # Degraded: NULL summary, empty refs.
        return None, []


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------


class LongDocIndexer:
    """Build and persist a hierarchical tree for a single long document.

    Parameters
    ----------
    conn : sqlite3.Connection
        Shared KnowledgeGraph connection. Must already have the long-doc
        tables (see ``mnemosyne.graph.longdoc_schema``).
    entity_types : list[str]
        Entity types passed to the SLM/LLM summariser.
    domain : str
        Domain label passed to the LLMBridge fallback.
    raw_root : Path or str
        REQUIRED. File paths read via ``index_file`` are validated against
        this root before reading (REQ-LD-008). A ``None`` value raises
        ``ValueError`` — the validator must never be skipped.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        entity_types: Optional[List[str]] = None,
        domain: str = "daily",
        raw_root: "str | Path | None" = None,
    ) -> None:
        if raw_root is None:
            raise ValueError(
                "raw_root is required for path validation (REQ-LD-008)"
            )
        self.conn = conn
        self.entity_types = list(entity_types or [])
        self.domain = domain
        self.raw_root = Path(raw_root)

    # -- public API --------------------------------------------------------

    def index_text(
        self,
        text: str,
        source_hash: str,
        kind: str = "markdown",
    ) -> Optional[str]:
        """Index a raw text blob. Returns the new ``tree_id`` or ``None``.

        ``kind`` selects the splitter: ``"markdown"`` (default) or ``"text"``
        (plain text treated as one section). PDF input must go through
        ``index_file`` because it needs ``pymupdf``.
        """
        if kind == "markdown":
            sections = split_markdown(text)
        else:
            tokens = _estimate_tokens(text)
            sections = [Section(
                title="root",
                body=text,
                token_start=0,
                token_end=tokens,
                ordinal=0,
            )]
        return self._index_sections(sections, source_hash)

    def index_file(self, path: "str | Path", source_hash: str) -> Optional[str]:
        """Index a file from disk. Markdown and PDF are auto-detected.

        REQ-LD-008: the path is ALWAYS validated against ``raw_root`` before
        reading — the validator is never skipped. R-LD-001: a file-size cap
        (``MAX_LONGDOC_BYTES``) is enforced before any read. PDF parsing
        raises ``ImportError`` when ``pymupdf`` is absent; the caller is
        expected to translate that into an ``ExtractionError(layer='longdoc')``
        and skip.
        """
        # Unconditional validation: REQ-LD-008 traversal guard always runs.
        resolved = validate_longdoc_path(path, self.raw_root)

        # R-LD-001 REVIEW-phase: file-size cap before any read.
        try:
            size = resolved.stat().st_size
        except OSError as exc:
            raise LongDocPathError(
                f"Cannot stat long-doc path {resolved}: {exc}"
            ) from exc
        if size > MAX_LONGDOC_BYTES:
            raise LongDocPathError(
                f"Long-doc file exceeds {MAX_LONGDOC_BYTES} byte cap "
                f"(got {size} bytes): {resolved}"
            )

        suffix = resolved.suffix.lower()
        if suffix == ".pdf":
            sections = split_pdf_pages(resolved)
        elif suffix in (".md", ".markdown"):
            sections = split_markdown(resolved.read_text(errors="ignore"))
        else:
            text = resolved.read_text(errors="ignore")
            tokens = _estimate_tokens(text)
            sections = [Section(
                title="root",
                body=text,
                token_start=0,
                token_end=tokens,
                ordinal=0,
            )]
        return self._index_sections(sections, source_hash)

    # -- internals ---------------------------------------------------------

    def _index_sections(
        self, sections: List[Section], source_hash: str
    ) -> Optional[str]:
        if not sections:
            return None

        roots = _build_tree(sections)
        all_nodes = _flatten(roots)
        if not all_nodes:
            return None

        # R-LD-001 REVIEW-phase: hard node cap to bound row growth.
        if len(all_nodes) > MAX_LONGDOC_NODES:
            raise LongDocPathError(
                f"Long-doc tree exceeds {MAX_LONGDOC_NODES} node cap "
                f"(got {len(all_nodes)} nodes)"
            )

        if len(all_nodes) > NODE_WARN_THRESHOLD:
            logger.warning(
                "Long-doc tree has %d nodes (> %d); consider chunking input",
                len(all_nodes), NODE_WARN_THRESHOLD,
            )

        summariser = _Summariser(self.entity_types, self.domain)
        # Root node ID is the first root's id (or a synthetic root when there
        # are multiple roots -- we create a virtual root for the tree).
        virtual_root_id: Optional[str] = None
        if len(roots) == 1:
            virtual_root_id = roots[0].node_id

        new_tree_id = str(uuid.uuid4())
        now = utc_now_iso()

        cursor = self.conn.cursor()

        # REQ-LD-006: supersede any prior active tree for this source_hash.
        # No DELETE; only a status flip + superseded_by back-reference.
        prior = cursor.execute(
            "SELECT tree_id FROM document_trees "
            "WHERE source_hash=? AND status='active'",
            (source_hash,),
        ).fetchall()
        for row in prior:
            cursor.execute(
                "UPDATE document_trees SET status='superseded', superseded_by=? "
                "WHERE tree_id=?",
                (new_tree_id, row["tree_id"] if isinstance(row, sqlite3.Row) else row[0]),
            )

        cursor.execute(
            "INSERT INTO document_trees "
            "(tree_id, source_hash, root_node_id, created_at, superseded_by, status) "
            "VALUES (?, ?, ?, ?, NULL, 'active')",
            (new_tree_id, source_hash, virtual_root_id, now),
        )

        # When there are multiple roots, insert a synthetic root node.
        nodes_to_write: List[TreeNode] = list(all_nodes)
        if len(roots) > 1:
            synthetic = TreeNode(
                node_id=str(uuid.uuid4()),
                parent_id=None,
                path="root",
                depth=-1,
                token_start=roots[0].token_start,
                token_end=roots[-1].token_end,
                ordinal=-1,
            )
            for r in roots:
                r.parent_id = synthetic.node_id
            # Synthetic root is written by the main node loop below (it has an
            # empty excerpt, so summary stays NULL). We only need to record it
            # as the tree's root_node_id and include it in the write list.
            cursor.execute(
                "UPDATE document_trees SET root_node_id=? WHERE tree_id=?",
                (synthetic.node_id, new_tree_id),
            )
            nodes_to_write = [synthetic] + nodes_to_write

        for node in nodes_to_write:
            if node.raw_excerpt:
                summary, refs = summariser.summarise(node.raw_excerpt)
            else:
                summary, refs = None, []
            node.summary = summary
            node.entity_refs = refs

            # REVIEW-phase mitigation: redact secrets from raw_excerpt and
            # entity_refs before persisting to tree_nodes.
            redacted_excerpt = redact(node.raw_excerpt)
            redacted_refs = [redact(r) for r in node.entity_refs]

            cursor.execute(
                "INSERT INTO tree_nodes "
                "(node_id, tree_id, parent_id, path, depth, token_start, token_end, "
                "summary, entity_refs, ordinal, raw_excerpt) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    node.node_id,
                    new_tree_id,
                    node.parent_id,
                    node.path,
                    node.depth,
                    node.token_start,
                    node.token_end,
                    node.summary,
                    json.dumps(redacted_refs),
                    node.ordinal,
                    redacted_excerpt,
                ),
            )

            # Mirror summary into FTS5 for retrieval (REQ-LD-004).
            if summary:
                try:
                    cursor.execute(
                        "INSERT INTO tree_node_fts (node_id, tree_id, summary) "
                        "VALUES (?, ?, ?)",
                        (node.node_id, new_tree_id, summary),
                    )
                except sqlite3.OperationalError:
                    # FTS table may not exist when FTS5 is unavailable; skip.
                    pass

        self.conn.commit()
        return new_tree_id
