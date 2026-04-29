"""Main ingestion orchestrator for mnemosyne add command."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from mnemosyne.ingest.llm_extractor import (
    LLMExtractor,
    ParsedIngestResult,
    is_code_file,
    is_supported_file,
)
from mnemosyne.ingest.url_fetcher import URLFetcher

if TYPE_CHECKING:
    from mnemosyne.graph.knowledge_graph import KnowledgeGraph
    from mnemosyne.ingest.llm_bridge import LLMBridge

logger = logging.getLogger(__name__)


_HIDDEN_PREFIXES: tuple[str, ...] = (".",)


@dataclass
class IngestResult:
    """Outcome of ingesting a single target (file or URL)."""

    source: str
    raw_path: Optional[Path] = None
    entities_added: int = 0
    relations_added: int = 0
    skipped: bool = False
    skip_reason: str = ""
    errors: list[str] = field(default_factory=list)


# @MX:ANCHOR: [AUTO] Ingester orchestrates URL/file/dir/text ingestion.
# @MX:REASON: Public facade called by CLI, Updater, and external scripts; fan_in >= 3.
class Ingester:
    """Top-level orchestrator: fetch -> extract -> persist."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        raw_root: Optional[Path] = None,
        llm_bridge: Optional["LLMBridge"] = None,
        dry_run: bool = False,
    ) -> None:
        self.db_path = db_path
        self.raw_root = raw_root or (Path.home() / "mnemosyne" / "raw")
        self.dry_run = dry_run
        self._llm_bridge = llm_bridge
        self._kg: Optional[KnowledgeGraph] = None
        self._extractor: Optional[LLMExtractor] = None
        self._fetcher: Optional[URLFetcher] = None

    # -- public API --

    def add(
        self,
        target: str,
        domain: str = "daily",
        scope_id: Optional[str] = None,
        source_channel: str = "cli",
        text: Optional[str] = None,
    ) -> IngestResult:
        """Ingest ``target`` (URL, file, dir) or inline ``text``."""
        if text is not None:
            return self._add_text(text, domain, scope_id, source_channel)

        if self._is_url(target):
            return self._add_url(target, domain, scope_id, source_channel)

        path = Path(target).expanduser()
        if path.is_dir():
            results = self._add_directory(path, domain, scope_id, source_channel)
            return self._merge_results(target, results)
        if path.is_file():
            return self._add_file(path, domain, scope_id, source_channel)

        return IngestResult(
            source=target,
            skipped=True,
            skip_reason=f"target not found: {target}",
            errors=[f"target not found: {target}"],
        )

    def add_directory(
        self,
        path: Path,
        domain: str = "daily",
        scope_id: Optional[str] = None,
        source_channel: str = "cli",
    ) -> list[IngestResult]:
        """Public helper for directory ingestion."""
        return self._add_directory(path, domain, scope_id, source_channel)

    # -- private helpers --

    @staticmethod
    def _is_url(target: str) -> bool:
        return target.startswith(("http://", "https://", "file://"))

    def _add_url(
        self,
        url: str,
        domain: str,
        scope_id: Optional[str],
        source_channel: str,
    ) -> IngestResult:
        try:
            raw_path = self._get_fetcher().fetch(
                url, domain=domain, raw_dir=self.raw_root / domain
            )
        except OSError as exc:
            logger.error("URL fetch failed for %s: %s", url, exc)
            return IngestResult(source=url, errors=[str(exc)])

        file_result = self._add_file(raw_path, domain, scope_id, source_channel)
        file_result.source = url
        file_result.raw_path = raw_path
        return file_result

    def _add_file(
        self,
        path: Path,
        domain: str,
        scope_id: Optional[str],
        source_channel: str,
    ) -> IngestResult:
        result = IngestResult(source=str(path), raw_path=path)

        if not is_supported_file(path):
            result.skipped = True
            result.skip_reason = f"unsupported extension: {path.suffix}"
            return result

        try:
            content_hash = self._hash_file(path)
        except OSError as exc:
            result.errors.append(f"hash failed: {exc}")
            return result

        if not self.dry_run and self._is_unchanged(path, content_hash):
            result.skipped = True
            result.skip_reason = "unchanged since last ingest"
            return result

        chosen_domain = "coding" if is_code_file(path) else domain
        parsed = self._get_extractor().extract_file(
            path,
            domain=chosen_domain,
            scope_id=scope_id,
            source_channel=source_channel,
        )

        if self.dry_run:
            result.entities_added = len(parsed.entities)
            result.relations_added = len(parsed.relations)
            return result

        added_e, added_r = self._store_result(parsed, scope_id, source_channel)
        result.entities_added = added_e
        result.relations_added = added_r

        self._record_hash(path, content_hash)
        return result

    def _add_directory(
        self,
        path: Path,
        domain: str,
        scope_id: Optional[str],
        source_channel: str,
    ) -> list[IngestResult]:
        results: list[IngestResult] = []
        for file_path in self._iter_files(path):
            try:
                results.append(
                    self._add_file(file_path, domain, scope_id, source_channel)
                )
            except (OSError, sqlite3.Error, ValueError) as exc:
                logger.error("Failed to ingest %s: %s", file_path, exc)
                results.append(IngestResult(source=str(file_path), errors=[str(exc)]))
        return results

    def _add_text(
        self,
        text: str,
        domain: str,
        scope_id: Optional[str],
        source_channel: str,
    ) -> IngestResult:
        synthetic_source = f"text://{uuid.uuid4().hex[:12]}"
        result = IngestResult(source=synthetic_source)

        parsed = self._get_extractor().extract_text(
            text,
            source_file=synthetic_source,
            domain=domain,
            scope_id=scope_id,
            source_channel=source_channel,
        )

        if self.dry_run:
            result.entities_added = len(parsed.entities)
            result.relations_added = len(parsed.relations)
            return result

        added_e, added_r = self._store_result(parsed, scope_id, source_channel)
        result.entities_added = added_e
        result.relations_added = added_r
        return result

    def _store_result(
        self,
        result: ParsedIngestResult,
        scope_id: Optional[str],
        source_channel: str,
    ) -> tuple[int, int]:
        from mnemosyne.graph.knowledge_graph import Entity, Relation

        kg = self._get_kg()
        added_entities = 0
        added_relations = 0
        now = datetime.now(timezone.utc).isoformat()

        # Build a set of valid entity IDs to validate edges later.
        existing_ids: set[str] = set()

        for ie in result.entities:
            if kg.get_entity(ie.id) is not None:
                existing_ids.add(ie.id)
                continue

            properties = dict(ie.properties)
            properties["confidence"] = ie.confidence
            properties["confidence_score"] = ie.confidence_score
            properties.setdefault("source_file", ie.source_file)
            properties.setdefault("label", ie.label)

            entity = Entity(
                id=ie.id,
                type=ie.type,
                name=ie.label,
                properties=properties,
                created_at=now,
                updated_at=now,
            )
            try:
                kg.add_entity(entity, scope_id=scope_id, source_channel=source_channel)
                added_entities += 1
                existing_ids.add(ie.id)
            except sqlite3.IntegrityError as exc:
                logger.debug("Duplicate entity %s: %s", ie.id, exc)
                existing_ids.add(ie.id)

        for rel in result.relations:
            if rel.source not in existing_ids and kg.get_entity(rel.source) is None:
                logger.debug("Skipping relation: missing source %s", rel.source)
                continue
            if rel.target not in existing_ids and kg.get_entity(rel.target) is None:
                logger.debug("Skipping relation: missing target %s", rel.target)
                continue

            rid = f"{rel.source}__{rel.relation}__{rel.target}"
            relation = Relation(
                id=rid,
                source_id=rel.source,
                target_id=rel.target,
                relation_type=rel.relation,
                properties={
                    "confidence": rel.confidence,
                    "confidence_score": rel.confidence_score,
                },
                created_at=now,
            )
            try:
                kg.add_relation(
                    relation, scope_id=scope_id, source_channel=source_channel
                )
                added_relations += 1
            except sqlite3.IntegrityError as exc:
                logger.debug("Duplicate relation %s: %s", rid, exc)

        return added_entities, added_relations

    @staticmethod
    def _iter_files(root: Path) -> list[Path]:
        results: list[Path] = []
        for child in sorted(root.rglob("*")):
            if not child.is_file():
                continue
            # Skip hidden directories
            if any(
                part.startswith(_HIDDEN_PREFIXES) for part in child.relative_to(root).parts
            ):
                continue
            if not is_supported_file(child):
                continue
            results.append(child)
        return results

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _is_unchanged(self, path: Path, content_hash: str) -> bool:
        kg = self._get_kg()
        self._ensure_cache_table(kg.conn)
        row = kg.conn.execute(
            "SELECT content_hash FROM ingest_cache WHERE file_path = ?",
            (str(path),),
        ).fetchone()
        return bool(row) and row["content_hash"] == content_hash

    def _record_hash(self, path: Path, content_hash: str) -> None:
        kg = self._get_kg()
        self._ensure_cache_table(kg.conn)
        kg.conn.execute(
            """
            INSERT INTO ingest_cache (file_path, content_hash, ingested_at)
            VALUES (?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                content_hash = excluded.content_hash,
                ingested_at = excluded.ingested_at
            """,
            (str(path), content_hash, datetime.now(timezone.utc).isoformat()),
        )
        kg.conn.commit()

    @staticmethod
    def _ensure_cache_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_cache (
                file_path TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    @staticmethod
    def _merge_results(source: str, results: list[IngestResult]) -> IngestResult:
        merged = IngestResult(source=source)
        for r in results:
            merged.entities_added += r.entities_added
            merged.relations_added += r.relations_added
            if r.errors:
                merged.errors.extend(r.errors)
        if not results:
            merged.skipped = True
            merged.skip_reason = "no supported files in directory"
        return merged

    def _get_kg(self) -> "KnowledgeGraph":
        if self._kg is None:
            from mnemosyne.graph.knowledge_graph import KnowledgeGraph

            self._kg = KnowledgeGraph(
                db_path=str(self.db_path) if self.db_path else None
            )
            self._ensure_cache_table(self._kg.conn)
        return self._kg

    def _get_extractor(self) -> LLMExtractor:
        if self._extractor is None:
            self._extractor = LLMExtractor(bridge=self._llm_bridge)
        return self._extractor

    def _get_fetcher(self) -> URLFetcher:
        if self._fetcher is None:
            self._fetcher = URLFetcher()
        return self._fetcher

    def close(self) -> None:
        """Close any persistent resources."""
        if self._kg is not None:
            self._kg.close()
            self._kg = None


def result_to_dict(result: IngestResult) -> dict[str, Any]:
    """Serialize an :class:`IngestResult` to a JSON-friendly dict."""
    return {
        "source": result.source,
        "raw_path": str(result.raw_path) if result.raw_path else None,
        "entities_added": result.entities_added,
        "relations_added": result.relations_added,
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "errors": list(result.errors),
    }
