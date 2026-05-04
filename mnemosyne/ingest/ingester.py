"""Main ingestion orchestrator for mnemosyne add command."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from mnemosyne.ingest.llm_extractor import (
    IngestEntity,
    LLMExtractor,
    ParsedIngestResult,
    is_code_file,
    is_supported_file,
)
from mnemosyne.ingest.url_fetcher import URLFetcher

if TYPE_CHECKING:
    from mnemosyne.graph.knowledge_graph import Entity
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
    wiki_paths: list[Path] = field(default_factory=list)
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
        wiki_root: Optional[Path] = None,
        include_wiki_excerpts: bool = False,
        llm_bridge: Optional["LLMBridge"] = None,
        dry_run: bool = False,
    ) -> None:
        self.db_path = db_path
        self.raw_root = raw_root or (Path.home() / "mnemosyne" / "raw")
        self.wiki_root = wiki_root
        self.include_wiki_excerpts = include_wiki_excerpts
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

    async def add_urls_async(
        self,
        urls: list[str],
        domain: str = "daily",
        scope_id: Optional[str] = None,
        source_channel: str = "cli",
        concurrency: int = 5,
    ) -> list[IngestResult]:
        """Fetch and ingest multiple URLs concurrently.

        Uses :meth:`URLFetcher.fetch_async` for parallel downloads capped at
        ``concurrency`` simultaneous requests.  The graph writes remain
        sequential (SQLite is not async).
        """
        fetcher = self._get_fetcher()
        sem = asyncio.Semaphore(concurrency)

        async def _fetch_one(url: str) -> tuple[str, Path | None, str]:
            async with sem:
                try:
                    path = await fetcher.fetch_async(
                        url, domain=domain, raw_dir=self.raw_root / domain
                    )
                    return url, path, ""
                except Exception as exc:  # noqa: BLE001
                    return url, None, str(exc)

        fetch_results = await asyncio.gather(*[_fetch_one(u) for u in urls])

        results: list[IngestResult] = []
        for url, raw_path, err in fetch_results:
            if err or raw_path is None:
                results.append(
                    IngestResult(source=url, errors=[err or "fetch returned None"])
                )
                continue
            # Extract + persist synchronously (SQLite is not async-safe across threads)
            file_result = self._add_file(raw_path, domain, scope_id, source_channel)
            file_result.source = url
            file_result.raw_path = raw_path
            results.append(file_result)
        return results

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
        result.wiki_paths = self._maintain_wiki(
            parsed,
            source=str(path),
            domain=chosen_domain,
            scope_id=scope_id,
            source_channel=source_channel,
            raw_path=path,
            original_source=result.source,
            content_hash=content_hash,
        )

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
        result.wiki_paths = self._maintain_wiki(
            parsed,
            source=synthetic_source,
            domain=domain,
            scope_id=scope_id,
            source_channel=source_channel,
            raw_path=None,
            original_source=synthetic_source,
            content_hash=None,
        )
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
            existing_entity = kg.get_entity(ie.id)
            if existing_entity is not None:
                merged = self._merge_entity(existing_entity, ie, scope_id, source_channel, now)
                kg.update_entity(merged, source_channel=source_channel)
                existing_ids.add(ie.id)
                continue

            properties = dict(ie.properties)
            properties["confidence"] = ie.confidence
            properties["confidence_score"] = ie.confidence_score
            properties.setdefault("source_file", ie.source_file)
            properties.setdefault("source_files", [ie.source_file] if ie.source_file else [])
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
                get_relation = getattr(kg, "get_relation", None)
                existing_relation = get_relation(rid) if callable(get_relation) else None
                if getattr(existing_relation, "id", None) != rid:
                    existing_relation = None
                if existing_relation is None:
                    kg.add_relation(
                        relation, scope_id=scope_id, source_channel=source_channel
                    )
                    added_relations += 1
                else:
                    relation.properties = self._merge_relation_properties(
                        existing_relation.properties, relation.properties
                    )
                    kg.update_relation(relation, source_channel=source_channel)
            except sqlite3.IntegrityError as exc:
                logger.debug("Duplicate relation %s: %s", rid, exc)

        return added_entities, added_relations

    @staticmethod
    def _merge_entity(
        existing: "Entity",
        incoming: "IngestEntity",
        scope_id: Optional[str],
        source_channel: str,
        now: str,
    ) -> "Entity":
        from mnemosyne.graph.knowledge_graph import Entity

        properties = dict(existing.properties)
        incoming_props = dict(incoming.properties)
        incoming_props["confidence"] = incoming.confidence
        incoming_props["confidence_score"] = incoming.confidence_score
        incoming_props.setdefault("source_file", incoming.source_file)
        incoming_props.setdefault("label", incoming.label)

        conflicts = dict(properties.get("conflicts") or {})
        for key, value in incoming_props.items():
            if value in (None, "", []):
                continue
            if key == "source_file":
                properties.setdefault("source_file", value)
                continue
            if key in properties and properties[key] not in (value, None, "", []):
                conflicts.setdefault(key, [])
                source_id = hashlib.sha1(str(incoming.source_file or "unknown").encode("utf-8")).hexdigest()[:10]
                conflict_entry = {
                    "existing": properties[key],
                    "incoming": value,
                    "source_file": incoming.source_file or "unknown",
                    "source_id": source_id if incoming.source_file else "unknown",
                    "detected_at": now,
                    "seen_at": now,
                    "resolution": "unresolved",
                }
                if not any(
                    isinstance(existing_conflict, dict)
                    and existing_conflict.get("existing") == conflict_entry["existing"]
                    and existing_conflict.get("incoming") == conflict_entry["incoming"]
                    and existing_conflict.get("source_file") == conflict_entry["source_file"]
                    for existing_conflict in conflicts[key]
                ):
                    conflicts[key].append(conflict_entry)
                continue
            properties[key] = value

        source_files = list(properties.get("source_files") or [])
        if incoming.source_file and incoming.source_file not in source_files:
            source_files.append(incoming.source_file)
        properties["source_files"] = source_files
        if conflicts:
            properties["conflicts"] = conflicts

        return Entity(
            id=existing.id,
            type=existing.type,
            name=existing.name or incoming.label,
            properties=properties,
            created_at=existing.created_at,
            updated_at=now,
            version=existing.version,
            scope_id=scope_id or existing.scope_id,
            source_channel=source_channel or existing.source_channel,
        )

    @staticmethod
    def _merge_relation_properties(
        existing: dict[str, Any], incoming: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(existing)
        for key, value in incoming.items():
            if value in (None, "", []):
                continue
            merged[key] = value
        return merged

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
            merged.wiki_paths.extend(r.wiki_paths)
        if not results:
            merged.skipped = True
            merged.skip_reason = "no supported files in directory"
        return merged

    def _maintain_wiki(
        self,
        parsed: ParsedIngestResult,
        *,
        source: str,
        domain: str,
        scope_id: Optional[str],
        source_channel: str,
        raw_path: Optional[Path],
        original_source: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> list[Path]:
        """Update the Markdown LLM Wiki when a wiki root was configured."""
        if self.wiki_root is None or self.dry_run:
            return []
        from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer

        update = LLMWikiMaintainer(
            self.wiki_root, include_excerpts=self.include_wiki_excerpts
        ).update_from_ingest(
            parsed,
            source=source,
            domain=domain,
            scope_id=scope_id,
            source_channel=source_channel,
            raw_path=raw_path,
            original_source=original_source,
            content_hash=content_hash,
        )
        return update.paths

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
        "wiki_paths": [str(path) for path in result.wiki_paths],
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "errors": list(result.errors),
    }
