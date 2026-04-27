"""
Extraction Pipeline Orchestration (SPEC-PIPE-001).

Provides IncrementalTracker, DomainRouter, ExtractionPipeline, ReportFormatter,
and CLI entry point for end-to-end extraction from source files to the
KnowledgeGraph SQLite store.
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from mnemosyne.extraction.pipeline_types import (
    ExtractionError,
    ExtractionReport,
    ExtractionResult,
    LayerStats,
    content_hash,
)

logger = logging.getLogger(__name__)


class IncrementalTracker:
    """REQ-003: Content-hash based incremental extraction tracking.

    Manages an ``extraction_tracking`` table inside an existing SQLite
    connection (shared with KnowledgeGraph).  Uses SHA-256 first-16-chars
    content hashes to detect file changes.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._create_table()

    def _create_table(self) -> None:
        """Create the extraction_tracking table (idempotent)."""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS extraction_tracking (
                file_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                domain TEXT NOT NULL,
                last_extracted_at TEXT NOT NULL,
                entity_count INTEGER DEFAULT 0,
                PRIMARY KEY (file_path, domain)
            )
        """)
        self.conn.commit()

    def get_changed_files(
        self,
        files: List[Path],
        hashes: Dict[Path, str],
        domain: str,
    ) -> List[Path]:
        """Return only files whose content hash differs from the last extraction."""
        cursor = self.conn.cursor()
        changed: List[Path] = []
        for f in files:
            row = cursor.execute(
                "SELECT content_hash FROM extraction_tracking WHERE file_path=? AND domain=?",
                (str(f), domain),
            ).fetchone()
            if row is None or row[0] != hashes[f]:
                changed.append(f)
        return changed

    def record_extraction(
        self,
        files: List[Path],
        hashes: Dict[Path, str],
        domain: str,
        entity_counts: Dict[Path, int],
    ) -> None:
        """Record (or update) extraction tracking entries for *files*."""
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()
        for f in files:
            cursor.execute(
                """INSERT INTO extraction_tracking (file_path, content_hash, domain, last_extracted_at, entity_count)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(file_path, domain) DO UPDATE SET
                       content_hash=excluded.content_hash,
                       last_extracted_at=excluded.last_extracted_at,
                       entity_count=excluded.entity_count
                """,
                (str(f), hashes[f], domain, now, entity_counts.get(f, 0)),
            )
        self.conn.commit()

    def cleanup_stale(self, existing_files: List[Path], domain: str) -> int:
        """Remove tracking records for files that no longer exist.

        Returns the number of removed records.
        """
        cursor = self.conn.cursor()
        existing_set = {str(f) for f in existing_files}
        # Find tracked files not in existing set.
        cursor.execute(
            "SELECT file_path FROM extraction_tracking WHERE domain=?", (domain,)
        )
        stale = [row[0] for row in cursor.fetchall() if row[0] not in existing_set]
        for file_path in stale:
            cursor.execute(
                "DELETE FROM extraction_tracking WHERE file_path=? AND domain=?",
                (file_path, domain),
            )
        self.conn.commit()
        return len(stale)


def _detect_error_patterns(errors: List[ExtractionError]) -> List[str]:
    """REQ-007: Detect error types occurring 3+ times and return warnings."""
    from collections import Counter
    type_counts = Counter(e.error_type for e in errors)
    warnings: List[str] = []
    for error_type, count in type_counts.items():
        if count >= 3:
            warnings.append(f"{error_type} repeated {count} times across files")
    return warnings


# -- Domain configuration ---------------------------------------------------

_DOMAIN_CONFIG: Dict[str, Dict[str, Any]] = {
    "coding": {
        "extensions": {
            ".py", ".js", ".ts", ".tsx", ".jsx",
            ".go", ".rs", ".java", ".cpp", ".c", ".rb",
        },
        "entity_types": [
            "function", "class", "module", "api", "bug",
            "feature", "test", "dependency",
        ],
        "deterministic_extractor": "tree_sitter",
    },
    "daily": {
        "extensions": {".txt", ".md", ".eml", ".json"},
        "entity_types": [
            "task", "person", "place", "event",
            "habit", "preference", "note",
        ],
        "deterministic_extractor": "spacy",
    },
    "legal": {
        "extensions": {".pdf", ".txt", ".md", ".docx"},
        "entity_types": [
            "statute", "clause", "case", "party",
            "obligation", "deadline", "contract",
        ],
        "deterministic_extractor": "spacy",
    },
}


class DomainRouter:
    """REQ-002: Maps a domain name to its extraction configuration.

    Attributes
    ----------
    domain : str
        The domain name (``coding``, ``daily``, ``legal``).
    file_extensions : set[str]
        File extensions supported by this domain.
    entity_types : list[str]
        Entity types defined in the domain schema.
    deterministic_extractor : str
        Key for the deterministic extractor (``tree_sitter`` or ``spacy``).
    """

    def __init__(self, domain: str) -> None:
        if domain not in _DOMAIN_CONFIG:
            supported = ", ".join(sorted(_DOMAIN_CONFIG))
            raise ValueError(
                f"Unsupported domain '{domain}'. Supported: {supported}"
            )
        cfg = _DOMAIN_CONFIG[domain]
        self.domain: str = domain
        self.file_extensions: Set[str] = cfg["extensions"]
        self.entity_types: List[str] = list(cfg["entity_types"])
        self.deterministic_extractor: str = cfg["deterministic_extractor"]

    def filter_files(self, files: List[Path]) -> List[Path]:
        """Return only files whose extension matches this domain."""
        return [f for f in files if f.suffix.lower() in self.file_extensions]


class ExtractionPipeline:
    """REQ-001: Orchestrates 3-layer extraction and stores results in KnowledgeGraph.

    Parameters
    ----------
    domain : str
        Extraction domain (``coding``, ``daily``, ``legal``).
    source : Path or str
        File or directory to extract from.
    knowledge_graph : KnowledgeGraph, optional
        Graph store.  If ``None``, a default path is used.
    scope_id : str, optional
        Scope identifier attached to all extracted entities.
    source_channel : str
        Source channel label (default ``"pipeline"``).
    enable_semantic : bool
        Whether to run the semantic extraction layer.
    enable_synthesis : bool
        Whether to run the synthesis extraction layer.
    incremental : bool
        Whether to skip unchanged files.
    """

    def __init__(
        self,
        domain: str,
        source: "Path | str",
        knowledge_graph: Any = None,
        scope_id: Optional[str] = None,
        source_channel: str = "pipeline",
        enable_semantic: bool = True,
        enable_synthesis: bool = True,
        incremental: bool = False,
    ) -> None:
        self.router = DomainRouter(domain)
        self.source = Path(source)
        self.scope_id = scope_id
        self.source_channel = source_channel
        self.enable_semantic = enable_semantic
        self.enable_synthesis = enable_synthesis
        self.incremental = incremental

        if knowledge_graph is not None:
            self.kg = knowledge_graph
        else:
            from mnemosyne.graph.knowledge_graph import KnowledgeGraph
            default_db = Path.home() / "agent-memory" / "mnemosyne" / "graph" / "knowledge.db"
            self.kg = KnowledgeGraph(str(default_db))

        self.tracker = IncrementalTracker(self.kg.conn)

        # Lazy-initialised extractors.
        self._tree_sitter: Any = None
        self._semantic: Any = None
        self._synthesis: Any = None

    # -- Lazy extractor accessors -------------------------------------------

    @property
    def tree_sitter(self) -> Any:
        if self._tree_sitter is None:
            from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor
            self._tree_sitter = TreeSitterExtractor()
        return self._tree_sitter

    @property
    def semantic(self) -> Any:
        if self._semantic is None:
            from mnemosyne.extraction.semantic.slm_extractor import SemanticExtractor
            self._semantic = SemanticExtractor()
        return self._semantic

    @property
    def synthesis(self) -> Any:
        if self._synthesis is None:
            from mnemosyne.extraction.synthesis.base import NoOpSynthesisExtractor
            self._synthesis = NoOpSynthesisExtractor()
        return self._synthesis

    # -- Public API ---------------------------------------------------------

    def run(self) -> ExtractionReport:
        """Execute the full extraction pipeline and return a report."""
        started_at = datetime.utcnow().isoformat()
        domain = self.router.domain

        # 1. Discover files
        all_files = self._discover_files()
        filtered = self.router.filter_files(all_files)
        files_discovered = len(filtered)

        # 2. Incremental: compute hashes and skip unchanged
        # Files that cannot be read for hashing are tracked separately.
        unreadable: List[Path] = []
        hashes: Dict[Path, str] = {}
        for f in filtered:
            try:
                hashes[f] = content_hash(f.read_bytes())
            except (PermissionError, OSError) as exc:
                unreadable.append(f)
                logger.warning("Cannot read %s for hashing: %s", f, exc)

        if self.incremental:
            to_process = self.tracker.get_changed_files(
                [f for f in filtered if f not in unreadable],
                hashes,
                domain,
            )
            files_skipped = files_discovered - len(to_process) - len(unreadable)
            self.tracker.cleanup_stale(filtered, domain)
        else:
            to_process = [f for f in filtered if f not in unreadable]
            files_skipped = 0

        # 3. Extract per file
        all_results: List[ExtractionResult] = []
        errors: List[ExtractionError] = []
        det_stats = LayerStats()
        sem_stats = LayerStats()
        syn_stats = LayerStats()

        # Record unreadable files as errors.
        for f in unreadable:
            errors.append(ExtractionError(
                file_path=str(f),
                error_type="PermissionError",
                error_message="Cannot read file for hashing",
                layer="discovery",
            ))

        for file_path in to_process:
            result = self._extract_file(file_path)
            all_results.append(result)
            errors.extend(result.errors)

            if "deterministic" in result.layers_used:
                det_stats.files_processed += 1
                det_stats.entities_extracted += len(
                    [e for e in result.entities if e.get("_layer") == "deterministic"]
                )
                det_stats.estimated_tokens += result.estimated_tokens

            if "semantic" in result.layers_used:
                sem_stats.files_processed += 1
                sem_stats.entities_extracted += len(
                    [e for e in result.entities if e.get("_layer") == "semantic"
                     or "_layer" not in e]
                ) - det_stats.entities_extracted if det_stats.files_processed == 0 else 0

            if "synthesis" in result.layers_used:
                syn_stats.files_processed += 1
                syn_stats.entities_extracted += len(
                    [e for e in result.entities if e.get("_layer") == "synthesis"]
                )

        files_failed = len([r for r in all_results if r.errors])
        files_processed = len(to_process) - files_failed

        # Merge and deduplicate entities across files.
        merged_entities, merged_relations = self._merge_results(all_results)

        # 4. Store to KnowledgeGraph
        entities_stored, relations_stored = self._store_results(
            merged_entities, merged_relations
        )

        total_entities = len(merged_entities)
        total_relations = len(merged_relations)

        # 5. Update incremental tracker
        entity_counts: Dict[Path, int] = {}
        for result in all_results:
            if not result.errors:
                p = Path(result.source)
                entity_counts[p] = len(result.entities)
        self.tracker.record_extraction(to_process, hashes, domain, entity_counts)

        completed_at = datetime.utcnow().isoformat()

        # Detect repeated error patterns.
        warnings = _detect_error_patterns(errors)

        return ExtractionReport(
            domain=domain,
            source=str(self.source),
            started_at=started_at,
            completed_at=completed_at,
            files_discovered=files_discovered,
            files_processed=files_processed,
            files_skipped=files_skipped,
            files_failed=files_failed + len(unreadable),
            entities_extracted=total_entities,
            entities_stored=entities_stored,
            relations_extracted=total_relations,
            relations_stored=relations_stored,
            layer_deterministic=det_stats,
            layer_semantic=sem_stats,
            layer_synthesis=syn_stats,
            errors=errors,
            warnings=warnings,
            estimated_tokens=sum(r.estimated_tokens for r in all_results),
            scope_id=self.scope_id,
            source_channel=self.source_channel,
        )

    # -- File discovery -----------------------------------------------------

    def _discover_files(self) -> List[Path]:
        """Return all regular files under *source* (recursively if directory)."""
        source = self.source
        if source.is_file():
            return [source]
        if source.is_dir():
            return sorted(f for f in source.rglob("*") if f.is_file())
        return []

    # -- Per-file extraction ------------------------------------------------

    def _extract_file(self, file_path: Path) -> ExtractionResult:
        """Run configured extraction layers on a single file."""
        errors: List[ExtractionError] = []
        entities: List[Dict[str, Any]] = []
        relations: List[Dict[str, Any]] = []
        layers_used: List[str] = []
        total_tokens = 0

        # Layer 1: Deterministic
        try:
            det_entities, det_rels = self._run_deterministic(file_path)
            for e in det_entities:
                e["_layer"] = "deterministic"
            entities.extend(det_entities)
            relations.extend(det_rels)
            layers_used.append("deterministic")
        except Exception as exc:
            errors.append(ExtractionError(
                file_path=str(file_path),
                error_type=type(exc).__name__,
                error_message=str(exc),
                layer="deterministic",
            ))
            # If deterministic fails, skip remaining layers.
            return ExtractionResult(
                source=str(file_path),
                entities=entities,
                relations=relations,
                errors=errors,
                layers_used=layers_used,
                estimated_tokens=total_tokens,
            )

        # Layer 2: Semantic (optional)
        if self.enable_semantic:
            try:
                sem_result = self._run_semantic(file_path, entities)
                sem_entities = sem_result.get("entities", [])
                sem_relations = sem_result.get("relations", [])
                for e in sem_entities:
                    e["_layer"] = "semantic"
                entities.extend(sem_entities)
                relations.extend(sem_relations)
                total_tokens += sem_result.get("token_cost", 0)
                layers_used.append("semantic")
            except Exception as exc:
                errors.append(ExtractionError(
                    file_path=str(file_path),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    layer="semantic",
                ))

        # Layer 3: Synthesis (optional)
        if self.enable_synthesis and self.synthesis.is_available:
            try:
                syn_result = self.synthesis.extract(
                    text=file_path.read_text(errors="ignore"),
                    existing_entities=entities,
                    domain=self.router.domain,
                    scope_id=self.scope_id,
                    source_channel=self.source_channel,
                )
                syn_entities = syn_result.get("entities", [])
                syn_relations = syn_result.get("relations", [])
                for e in syn_entities:
                    e["_layer"] = "synthesis"
                entities.extend(syn_entities)
                relations.extend(syn_relations)
                total_tokens += syn_result.get("token_cost", 0)
                layers_used.append("synthesis")
            except Exception as exc:
                errors.append(ExtractionError(
                    file_path=str(file_path),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    layer="synthesis",
                ))

        return ExtractionResult(
            source=str(file_path),
            entities=entities,
            relations=relations,
            errors=errors,
            layers_used=layers_used,
            estimated_tokens=total_tokens,
        )

    def _run_deterministic(
        self, file_path: Path
    ) -> tuple:
        """Run deterministic extraction (TreeSitter or SpaCy)."""
        if self.router.deterministic_extractor == "tree_sitter":
            return self._run_tree_sitter(file_path)
        else:
            return self._run_spacy(file_path)

    def _run_tree_sitter(self, file_path: Path) -> tuple:
        """Extract using TreeSitterExtractor."""
        parse_result = self.tree_sitter.extract_file_full(
            file_path,
            scope_id=self.scope_id,
            source_channel=self.source_channel,
        )
        entities: List[Dict[str, Any]] = []
        for ce in parse_result.entities:
            entities.append({
                "type": ce.type,
                "name": ce.name,
                "file_path": ce.file_path,
                "line_start": ce.line_start,
                "line_end": ce.line_end,
                "language": ce.language,
                "properties": ce.properties,
            })

        relations: List[Dict[str, Any]] = []
        # Call graph relations
        for call in parse_result.calls:
            relations.append({
                "source_name": call.caller_name,
                "target_name": call.callee_name,
                "relation_type": "calls",
                "properties": {
                    "call_type": call.call_type,
                    "line": call.callee_line,
                },
            })

        return entities, relations

    def _run_spacy(self, file_path: Path) -> tuple:
        """Extract using SpaCyExtractor (for daily/legal domains)."""
        from mnemosyne.extraction.deterministic.code_parser import SpaCyExtractor
        spacy_ext = SpaCyExtractor()
        text = file_path.read_text(errors="ignore")
        raw_entities = spacy_ext.extract_entities(text)
        raw_relations = spacy_ext.extract_relations(text)

        entities = []
        for ent in raw_entities:
            entities.append({
                "type": ent.get("type", "unknown"),
                "name": ent.get("text", ""),
                "file_path": str(file_path),
                "properties": {
                    "start": ent.get("start", 0),
                    "end": ent.get("end", 0),
                },
            })

        relations = []
        for rel in raw_relations:
            relations.append({
                "source_name": rel.get("subject", ""),
                "target_name": rel.get("object", ""),
                "relation_type": rel.get("verb", "related_to"),
            })

        return entities, relations

    def _run_semantic(
        self, file_path: Path, existing_entities: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Run semantic extraction (GLiNER2 + REBEL)."""
        text = file_path.read_text(errors="ignore")
        return self.semantic.extract(
            text=text,
            entity_types=self.router.entity_types,
            scope_id=self.scope_id,
            source_channel=self.source_channel,
        )

    # -- Merge results ------------------------------------------------------

    def _merge_results(
        self, results: List[ExtractionResult]
    ) -> tuple:
        """Merge entities across files, deduplicating by (type, name, file_path)."""
        seen: Dict[tuple, Dict[str, Any]] = {}
        all_relations: List[Dict[str, Any]] = []

        for result in results:
            if result.errors:
                continue
            for entity in result.entities:
                key = (
                    entity.get("type", ""),
                    entity.get("name", ""),
                    entity.get("file_path", ""),
                )
                if key in seen:
                    # Merge properties from both layers.
                    existing_props = seen[key].get("properties", {})
                    new_props = entity.get("properties", {})
                    merged = {**existing_props, **new_props}
                    seen[key]["properties"] = merged
                else:
                    seen[key] = dict(entity)

            all_relations.extend(result.relations)

        return list(seen.values()), all_relations

    # -- Store results to KnowledgeGraph ------------------------------------

    def _store_results(
        self,
        entities: List[Dict[str, Any]],
        relations: List[Dict[str, Any]],
    ) -> tuple:
        """Store entities and relations into KnowledgeGraph with dedup/upsert.

        Uses two-pass: store all entities first, then resolve names to IDs
        for relations.

        Returns (entities_stored, relations_stored).
        """
        from mnemosyne.graph.knowledge_graph import Entity, Relation

        name_to_id: Dict[str, str] = {}
        entities_stored = 0
        relations_stored = 0
        now = datetime.utcnow().isoformat()

        # Pass 1: Store entities
        for ent_dict in entities:
            try:
                ent_type = ent_dict.get("type", "unknown")
                ent_name = ent_dict.get("name", "unknown")
                file_path = ent_dict.get("file_path", "")
                props = ent_dict.get("properties", {})
                # Include metadata in properties.
                full_props = {
                    "file_path": file_path,
                    **props,
                }
                for key in ("line_start", "line_end", "language"):
                    if key in ent_dict:
                        full_props[key] = ent_dict[key]
                full_props.pop("_layer", None)

                # Dedup check: upsert by (type, name, scope_id).
                cursor = self.kg.conn.cursor()
                existing = cursor.execute(
                    "SELECT id, version FROM entities WHERE type=? AND name=? AND scope_id=?",
                    (ent_type, ent_name, self.scope_id),
                ).fetchone()

                if existing:
                    entity_id = existing[0]
                    new_version = existing[1] + 1
                    cursor.execute(
                        "UPDATE entities SET properties=?, updated_at=?, version=? WHERE id=?",
                        (json.dumps(full_props), now, new_version, entity_id),
                    )
                    self.kg.conn.commit()
                else:
                    entity_id = str(uuid.uuid4())
                    kg_entity = Entity(
                        id=entity_id,
                        type=ent_type,
                        name=ent_name,
                        properties=full_props,
                        created_at=now,
                        updated_at=now,
                    )
                    self.kg.add_entity(
                        kg_entity,
                        scope_id=self.scope_id,
                        source_channel=self.source_channel,
                    )

                name_to_id[f"{ent_type}:{ent_name}"] = entity_id
                name_to_id[ent_name] = entity_id
                entities_stored += 1

            except Exception as exc:
                logger.error("Failed to store entity %s: %s", ent_dict.get("name"), exc)

        # Pass 2: Store relations (resolve names to IDs).
        for rel_dict in relations:
            try:
                source_name = rel_dict.get("source_name", "")
                target_name = rel_dict.get("target_name", "")
                rel_type = rel_dict.get("relation_type", "related_to")
                rel_props = rel_dict.get("properties", {})

                source_id = name_to_id.get(source_name)
                target_id = name_to_id.get(target_name)

                if source_id and target_id:
                    rel_id = str(uuid.uuid4())
                    kg_rel = Relation(
                        id=rel_id,
                        source_id=source_id,
                        target_id=target_id,
                        relation_type=rel_type,
                        properties=rel_props,
                        created_at=now,
                    )
                    self.kg.add_relation(
                        kg_rel,
                        scope_id=self.scope_id,
                        source_channel=self.source_channel,
                    )
                    relations_stored += 1
                else:
                    logger.debug(
                        "Skipping relation %s -> %s: unresolved names",
                        source_name, target_name,
                    )
            except Exception as exc:
                logger.error("Failed to store relation: %s", exc)

        return entities_stored, relations_stored


class ReportFormatter:
    """REQ-006: Format ExtractionReport for terminal output."""

    @staticmethod
    def format_summary(report: ExtractionReport) -> str:
        """Human-readable table format for terminal output."""
        lines = [
            f"Extraction Report: {report.domain}",
            f"Source: {report.source}",
            f"Duration: {report.started_at} -> {report.completed_at}",
            "",
            f"Files discovered : {report.files_discovered}",
            f"Files processed  : {report.files_processed}",
            f"Files skipped    : {report.files_skipped}",
            f"Files failed     : {report.files_failed}",
            "",
            f"Entities extracted: {report.entities_extracted}",
            f"Entities stored   : {report.entities_stored}",
            f"Relations extracted: {report.relations_extracted}",
            f"Relations stored   : {report.relations_stored}",
            "",
            f"Estimated tokens : {report.estimated_tokens}",
        ]
        if report.scope_id:
            lines.append(f"Scope ID         : {report.scope_id}")
        if report.errors:
            lines.append("")
            lines.append(f"Errors ({len(report.errors)}):")
            for err in report.errors:
                lines.append(f"  [{err.error_type}] {err.file_path}: {err.error_message}")
        if report.warnings:
            lines.append("")
            for w in report.warnings:
                lines.append(f"WARNING: {w}")
        return "\n".join(lines)

    @staticmethod
    def format_json(report: ExtractionReport) -> str:
        """JSON-serialised ExtractionReport."""
        from dataclasses import asdict
        return json.dumps(asdict(report), indent=2, default=str)

    @staticmethod
    def format_wiki(report: ExtractionReport) -> str:
        """Wiki markdown format with [[wiki-links]]."""
        lines = [
            f"# Extraction Report: [[domain:{report.domain}]]",
            "",
            f"**Source**: `[[file:{report.source}]]`",
            f"**Scope**: {report.scope_id or 'global'}",
            "",
            "## Statistics",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| Files discovered | {report.files_discovered} |",
            f"| Files processed | {report.files_processed} |",
            f"| Files skipped | {report.files_skipped} |",
            f"| Entities extracted | {report.entities_extracted} |",
            f"| Relations extracted | {report.relations_extracted} |",
            "",
            "## Layers",
            "",
            f"- **Deterministic**: {report.layer_deterministic.entities_extracted} entities",
            f"- **Semantic**: {report.layer_semantic.entities_extracted} entities",
            f"- **Synthesis**: {report.layer_synthesis.entities_extracted} entities",
        ]
        if report.errors:
            lines.append("")
            lines.append("## Errors")
            for err in report.errors:
                lines.append(f"- `[[file:{err.file_path}]]` [{err.error_type}]: {err.error_message}")
        return "\n".join(lines)


def build_parser():
    """Build the argparse parser for the pipeline CLI."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="python -m mnemosyne.extraction.pipeline",
        description="Extraction Pipeline: extract entities and relations from source files",
    )
    parser.add_argument(
        "--domain", required=True, choices=["coding", "daily", "legal"],
        help="Extraction domain",
    )
    parser.add_argument(
        "--source", required=True,
        help="File or directory path to extract from",
    )
    parser.add_argument(
        "--scope-id", default=None,
        help="Scope identifier for extracted entities",
    )
    parser.add_argument(
        "--source-channel", default="pipeline",
        help="Source channel label (default: pipeline)",
    )
    parser.add_argument(
        "--format", default="summary", choices=["summary", "json", "wiki"],
        help="Output format (default: summary)",
    )
    parser.add_argument(
        "--incremental", action="store_true", default=False,
        help="Enable incremental extraction (skip unchanged files)",
    )
    parser.add_argument(
        "--no-semantic", action="store_true", default=False,
        help="Disable semantic extraction layer",
    )
    parser.add_argument(
        "--db-path", default=None,
        help="Path to KnowledgeGraph SQLite database",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for the extraction pipeline."""
    import sys

    parser = build_parser()

    # Let argparse handle its own SystemExit for --help and missing args.
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.exists():
        print(f"Error: Source path not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    # Resolve DB path.
    if args.db_path:
        db_path = args.db_path
    else:
        db_path = str(
            Path.home() / "agent-memory" / "mnemosyne" / "graph" / "knowledge.db"
        )

    from mnemosyne.graph.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph(db_path)

    try:
        pipeline = ExtractionPipeline(
            domain=args.domain,
            source=source,
            knowledge_graph=kg,
            scope_id=args.scope_id,
            source_channel=args.source_channel,
            enable_semantic=not args.no_semantic,
            incremental=args.incremental,
        )
        report = pipeline.run()

        # Format output.
        if args.format == "json":
            print(ReportFormatter.format_json(report))
        elif args.format == "wiki":
            print(ReportFormatter.format_wiki(report))
        else:
            print(ReportFormatter.format_summary(report))

        # Exit code.
        if report.files_discovered > 0 and report.files_processed == 0 and report.files_failed > 0:
            # All files failed.
            print(
                f"All {report.files_failed} files failed extraction.",
                file=sys.stderr,
            )
            sys.exit(2)
        else:
            sys.exit(0)

    finally:
        kg.close()


if __name__ == "__main__":
    main()
