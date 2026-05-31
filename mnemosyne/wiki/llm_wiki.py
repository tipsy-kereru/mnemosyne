"""Markdown LLM Wiki maintenance for ingested knowledge.

The wiki is the human/LLM-readable layer. Raw sources and the structured graph
remain the durable source of truth; generated Markdown sections are rebuildable
views that preserve manual notes outside generated markers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from mnemosyne.ingest.llm_extractor import IngestEntity, IngestRelation, ParsedIngestResult

try:
    from mnemosyne import mnemosyne_core
    _HAS_RUST_CORE = True
except ImportError:
    _HAS_RUST_CORE = False

_GENERATED_START = "<!-- MNEMOSYNE:GENERATED:START -->"
_GENERATED_END = "<!-- MNEMOSYNE:GENERATED:END -->"
_EDITOR_GUIDANCE_LINES = [
    "## Editing guidance",
    "",
    "- This generated section is replaced by `mnemosyne add`, `mnemosyne update`, and `mnemosyne wiki rebuild`.",
    "- Add human notes outside the `MNEMOSYNE:GENERATED` markers, preferably under `## Notes`.",
    "- Raw sources plus the graph database remain authoritative; editor pages are readable views plus manual notes.",
]
_MAX_SOURCE_EXCERPT = 1200
_DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_POLL_INTERVAL_SECONDS = 0.05
_CONFLICT_RESOLUTION_STATUSES = {
    "unresolved",
    "accepted_existing",
    "accepted_incoming",
    "superseded",
    "ambiguous",
}
_RESOLVED_CONFLICT_STATUSES = _CONFLICT_RESOLUTION_STATUSES - {"unresolved"}
_SEMANTIC_REVIEW_SCHEMA = "mnemosyne.semantic_contradiction_candidates.v1"
_SEMANTIC_REVIEW_STATUS_OPEN = {"candidate", "needs_review"}
_STATUS_CONTRADICTION_PAIRS = {
    frozenset(("active", "inactive")),
    frozenset(("open", "closed")),
    frozenset(("pending", "completed")),
    frozenset(("pending", "done")),
    frozenset(("approved", "rejected")),
    frozenset(("current", "former")),
    frozenset(("enabled", "disabled")),
    frozenset(("yes", "no")),
    frozenset(("true", "false")),
}
_STATUS_PROPERTIES = {"status", "state", "stage", "lifecycle"}
_DATE_PROPERTIES = {"date", "due_date", "deadline", "start_date", "end_date"}
_RESPONSIBILITY_PROPERTIES = {"owner", "assignee", "responsible", "role"}
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(secret\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(token\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{12,}"), "sk-[REDACTED]"),
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[EMAIL_REDACTED]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN_REDACTED]"),
)




class WikiLockError(RuntimeError):
    """Raised when a wiki write lock cannot be acquired safely."""

    def __init__(
        self,
        lock_path: Path,
        *,
        timeout_seconds: float,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.lock_path = lock_path
        self.timeout_seconds = timeout_seconds
        self.metadata = metadata or {}
        holder = f" Current holder metadata: {self.metadata}" if self.metadata else ""
        super().__init__(
            "Could not acquire Mnemosyne wiki write lock "
            f"at {lock_path} within {timeout_seconds:g}s. "
            "Another Mnemosyne writer may be active; retry later. "
            "If the owning process is gone, inspect the lock metadata before removing it."
            f"{holder}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": "wiki-lock-timeout",
            "lock_path": str(self.lock_path),
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
            "message": str(self),
        }


@dataclass
class WikiWriteLock:
    """Stdlib-only single-writer lock for a wiki root."""

    wiki_root: Path
    timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SECONDS
    poll_interval_seconds: float = _LOCK_POLL_INTERVAL_SECONDS
    action: str = "wiki-write"

    def __post_init__(self) -> None:
        self.wiki_root = self.wiki_root.expanduser()
        lock_dir_env = os.environ.get("MNEMOSYNE_LOCK_DIR")
        if lock_dir_env:
            lock_dir = Path(lock_dir_env).expanduser()
            lock_dir.mkdir(parents=True, exist_ok=True)
            root_hash = uuid.uuid5(uuid.NAMESPACE_DNS, str(self.wiki_root)).hex[:12]
            self.lock_path = lock_dir / f".mnemosyne-wiki-{root_hash}.lock"
        else:
            self.lock_path = self.wiki_root / ".mnemosyne-wiki.lock"
        self.owner_token = uuid.uuid4().hex
        self._acquired = False

    def __enter__(self) -> "WikiWriteLock":
        self.wiki_root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(0.0, self.timeout_seconds)
        while True:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise WikiLockError(
                        self.lock_path,
                        timeout_seconds=self.timeout_seconds,
                        metadata=self.read_metadata(self.lock_path),
                    ) from None
                time.sleep(self.poll_interval_seconds)
                continue
            metadata = self._metadata()
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(metadata, fh, indent=2, sort_keys=True)
                fh.write("\n")
            self._acquired = True
            return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()

    def release(self) -> None:
        """Release only the lock owned by this context."""
        if not self._acquired:
            return
        metadata = self.read_metadata(self.lock_path)
        if metadata.get("owner_token") == self.owner_token:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
        self._acquired = False

    def is_stale(self, *, max_age_seconds: float) -> bool:
        """Return true for an existing lock older than ``max_age_seconds``.

        This is diagnostic only; stale locks are never broken automatically.
        """
        metadata = self.read_metadata(self.lock_path)
        created_at = str(metadata.get("created_at", ""))
        if not created_at:
            return False
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - created.astimezone(timezone.utc)
        return age.total_seconds() > max_age_seconds

    @staticmethod
    def read_metadata(lock_path: Path) -> dict[str, Any]:
        try:
            return json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _metadata(self) -> dict[str, Any]:
        return {
            "owner_token": self.owner_token,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "action": self.action,
            "wiki_root": str(self.wiki_root),
        }


@dataclass(frozen=True)
class WikiUpdate:
    """Files touched by one wiki maintenance pass."""

    paths: list[Path]


@dataclass(frozen=True)
class WikiContradiction:
    """Normalized, deterministic conflict metadata promoted for review."""

    conflict_id: str
    entity_id: str
    entity_label: str
    property_name: str
    existing: Any
    incoming: Any
    source_file: str = "unknown"
    source_id: str = "unknown"
    detected_at: str = "unknown"
    resolution: str = "unresolved"
    reviewer: str = ""
    review_note: str = ""
    reviewed_at: str = ""

    @property
    def unresolved(self) -> bool:
        return self.resolution == "unresolved"


@dataclass(frozen=True)
class WikiStaleCandidate:
    """Non-destructive stale wiki/graph lifecycle candidate."""

    candidate_id: str
    kind: str
    reason: str
    risk: str
    path: str = ""
    entity_id: str = ""
    source_id: str = ""
    source: str = ""
    manual_note_preview: str = ""
    recommended_action: str = "review"


@dataclass(frozen=True)
class WikiSemanticEvidence:
    """Bounded evidence for an opt-in semantic contradiction review candidate."""

    entity_id: str
    entity_label: str
    entity_type: str
    source_file: str
    source_id: str
    property_name: str
    excerpt: str
    excerpt_kind: str = "property-value"


@dataclass(frozen=True)
class WikiSemanticContradictionCandidate:
    """Offline semantic review candidate; not a truth judgment or graph mutation."""

    candidate_id: str
    subject_label: str
    subject_type: str
    claim_type: str
    detector: str
    processing_mode: str
    confidence: float
    uncertainty: str
    rationale: str
    evidence: list[WikiSemanticEvidence]
    generated_at: str
    status: str = "candidate"
    remote_model: bool = False


@dataclass(frozen=True)
class WikiLintIssue:
    """A single wiki lint issue."""

    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class WikiLintReport:
    """Machine-readable wiki lint report."""

    wiki_root: str
    errors: list[WikiLintIssue] = field(default_factory=list)
    warnings: list[WikiLintIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "wiki_root": self.wiki_root,
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [issue.__dict__ for issue in self.errors],
            "warnings": [issue.__dict__ for issue in self.warnings],
        }


class LLMWikiMaintainer:
    """Create, lint, and rebuild a persistent Markdown LLM Wiki."""

    def __init__(
        self,
        wiki_root: Path | str,
        *,
        include_excerpts: bool = False,
        lock_timeout: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.wiki_root = Path(wiki_root).expanduser()
        self.include_excerpts = include_excerpts
        self.lock_timeout = lock_timeout

    @contextmanager
    def write_lock(self, action: str = "wiki-write") -> Iterator[WikiWriteLock]:
        """Acquire the wiki-root write lock for generated page writes."""
        lock = WikiWriteLock(self.wiki_root, timeout_seconds=self.lock_timeout, action=action)
        with lock:
            yield lock

    def lock_metadata(self) -> dict[str, Any]:
        """Return current lock metadata for diagnostics, if any."""
        return WikiWriteLock.read_metadata(self.wiki_root / ".mnemosyne-wiki.lock")

    def is_lock_stale(self, *, max_age_seconds: float) -> bool:
        """Diagnostic stale-lock check; never breaks locks automatically."""
        return WikiWriteLock(self.wiki_root).is_stale(max_age_seconds=max_age_seconds)

    def update_from_ingest(
        self,
        parsed: ParsedIngestResult,
        *,
        source: str,
        domain: str,
        scope_id: Optional[str] = None,
        source_channel: str = "cli",
        raw_path: Optional[Path] = None,
        original_source: Optional[str] = None,
        content_hash: Optional[str] = None,
        log_event: bool = True,
    ) -> WikiUpdate:
        """Update source/entity pages plus ``index.md`` and optionally ``log.md``."""
        with self.write_lock("update_from_ingest"):
            return self._update_from_ingest_unlocked(
                parsed,
                source=source,
                domain=domain,
                scope_id=scope_id,
                source_channel=source_channel,
                raw_path=raw_path,
                original_source=original_source,
                content_hash=content_hash,
                log_event=log_event,
            )

    def _update_from_ingest_unlocked(
        self,
        parsed: ParsedIngestResult,
        *,
        source: str,
        domain: str,
        scope_id: Optional[str] = None,
        source_channel: str = "cli",
        raw_path: Optional[Path] = None,
        original_source: Optional[str] = None,
        content_hash: Optional[str] = None,
        log_event: bool = True,
    ) -> WikiUpdate:
        self._ensure_dirs()

        touched: list[Path] = []
        source_page = self._write_source_page(
            parsed,
            source=source,
            domain=domain,
            scope_id=scope_id,
            source_channel=source_channel,
            raw_path=raw_path,
            original_source=original_source or source,
            content_hash=content_hash,
        )
        touched.append(source_page)

        for entity in sorted(parsed.entities, key=lambda e: (e.type, e.label, e.id)):
            relations = self._relations_for_entity(entity.id, parsed.relations)
            touched.append(
                self._write_entity_page(
                    entity,
                    relations=relations,
                    source_page=source_page,
                    scope_id=scope_id,
                    source_channel=source_channel,
                )
            )

        touched.append(self._write_index())
        if log_event:
            touched.append(
                self._append_log(
                    source=source,
                    domain=domain,
                    scope_id=scope_id,
                    source_channel=source_channel,
                    source_page=source_page,
                    entities=len(parsed.entities),
                    relations=len(parsed.relations),
                )
            )

        return WikiUpdate(paths=self._dedupe_paths(touched))

    def status(self, *, db_path: Optional[Path | str] = None) -> dict[str, Any]:
        """Return read-only wiki health/status information."""
        entity_pages = sorted((self.wiki_root / "entities").glob("*/*.md"))
        source_pages = sorted((self.wiki_root / "sources").glob("*/*.md"))
        all_pages = sorted(self.wiki_root.rglob("*.md")) if self.wiki_root.exists() else []
        report = self.lint(db_path=db_path)
        stats: dict[str, Any] = {}
        contradictions: dict[str, Any] = self._contradiction_stats(db_path)
        stale: dict[str, Any] = self._stale_stats(db_path)
        semantic: dict[str, Any] = self._semantic_stats()
        if db_path is not None and Path(db_path).expanduser().exists():
            from mnemosyne.graph.knowledge_graph import KnowledgeGraph

            kg = KnowledgeGraph(str(Path(db_path).expanduser()))
            try:
                stats = kg.get_stats()
            finally:
                kg.close()

        return {
            "wiki_root": str(self.wiki_root),
            "exists": self.wiki_root.exists(),
            "pages": len(all_pages),
            "entity_pages": len(entity_pages),
            "source_pages": len(source_pages),
            "last_log_entry": self._last_log_entry(),
            "broken_links": sum(1 for i in report.errors if i.code == "broken-link"),
            "lint_errors": len(report.errors),
            "lint_warnings": len(report.warnings),
            "graph": stats,
            "contradictions": contradictions,
            "stale": stale,
            "semantic_contradictions": semantic,
        }

    def lint(self, *, db_path: Optional[Path | str] = None) -> WikiLintReport:
        """Detect broken links, metadata gaps, malformed blocks, and graph/wiki drift."""
        errors: list[WikiLintIssue] = []
        warnings: list[WikiLintIssue] = []
        if not self.wiki_root.exists():
            return WikiLintReport(
                wiki_root=str(self.wiki_root),
                warnings=[
                    WikiLintIssue(
                        "warning", "missing-wiki-root", str(self.wiki_root), "Wiki root does not exist"
                    )
                ],
            )

        pages = sorted(self.wiki_root.rglob("*.md"))
        page_stems = {p.relative_to(self.wiki_root).with_suffix("").as_posix() for p in pages}
        page_names = {p.stem for p in pages}
        seen_meta_keys: dict[tuple[str, str], Path] = {}

        for page in pages:
            text = page.read_text(encoding="utf-8")
            rel = page.relative_to(self.wiki_root).as_posix()
            start_count = text.count(_GENERATED_START)
            end_count = text.count(_GENERATED_END)
            if start_count != end_count:
                errors.append(WikiLintIssue("error", "malformed-generated-block", rel, "Generated marker count mismatch"))

            frontmatter = self._parse_frontmatter(text)
            if self._requires_frontmatter(page) and not frontmatter:
                errors.append(WikiLintIssue("error", "missing-frontmatter", rel, "Required YAML frontmatter is missing"))
            if frontmatter:
                page_type = str(frontmatter.get("page_type", ""))
                identity = str(frontmatter.get("entity_id") or frontmatter.get("source_id") or "")
                if page_type and identity:
                    key = (page_type, identity)
                    if key in seen_meta_keys and seen_meta_keys[key] != page:
                        warnings.append(WikiLintIssue("warning", "duplicate-identity", rel, f"Same {page_type} identity as {seen_meta_keys[key]}"))
                    seen_meta_keys[key] = page

            for target in self._extract_wiki_links(text):
                if target.startswith(("http://", "https://", "graph:", "entity:")):
                    continue
                target_path = target.split("|", 1)[0].split("#", 1)[0]
                if target_path not in page_stems and Path(target_path).name not in page_names:
                    errors.append(WikiLintIssue("error", "broken-link", rel, f"Broken link: [[{target}]]"))

        self._add_graph_drift_warnings(db_path, warnings)
        self._add_contradiction_warnings(db_path, warnings)
        self._add_stale_warnings(db_path, warnings)
        self._add_semantic_warnings(warnings)
        return WikiLintReport(str(self.wiki_root), errors=errors, warnings=warnings)

    def stale_plan(self, db_path: Path | str) -> dict[str, Any]:
        """Return a non-destructive stale wiki/graph reconciliation plan."""
        candidates = self._stale_candidates(db_path)
        return self._stale_plan_payload(candidates, dry_run=True, tombstone_paths=[])

    def write_tombstones(self, db_path: Path | str) -> dict[str, Any]:
        """Write tombstone records for stale candidates without deleting pages/facts."""
        candidates = self._stale_candidates(db_path)
        tombstone_paths: list[str] = []
        with self.write_lock("write_tombstones"):
            for candidate in candidates:
                path = self._write_tombstone(candidate)
                tombstone_paths.append(str(path))
        return self._stale_plan_payload(candidates, dry_run=False, tombstone_paths=tombstone_paths)

    def discover_semantic_contradictions(
        self,
        db_path: Path | str,
        *,
        write: bool = False,
        include_raw_excerpts: bool = False,
    ) -> dict[str, Any]:
        """Run explicit offline semantic contradiction discovery.

        The detector is intentionally conservative and local-only. It emits
        review candidates in a schema that is separate from deterministic graph
        conflict metadata and never mutates graph facts.
        """
        candidates = self._semantic_candidates(db_path, include_raw_excerpts=include_raw_excerpts)
        payload = self._semantic_payload(candidates, persisted=False)
        if write:
            with self.write_lock("write_semantic_contradictions"):
                json_path = self._write_semantic_candidates_json(payload)
                markdown_path = self._write_semantic_candidates_page(payload)
            payload["persisted"] = True
            payload["paths"] = [str(json_path), str(markdown_path)]
        return payload

    def list_semantic_contradictions(self) -> dict[str, Any]:
        """Return persisted semantic review candidates without re-running discovery."""
        path = self._semantic_candidates_json_path()
        if not path.exists():
            return self._empty_semantic_payload(persisted=False)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                **self._empty_semantic_payload(persisted=False),
                "read_error": f"Could not parse {path}",
            }
        if payload.get("schema") != _SEMANTIC_REVIEW_SCHEMA:
            payload["schema_warning"] = f"unexpected schema: {payload.get('schema')}"
        payload.setdefault("persisted", True)
        payload.setdefault("paths", [str(path)])
        payload.setdefault("count", len(payload.get("candidates") or []))
        return payload

    def list_contradictions(
        self,
        db_path: Path | str,
        *,
        include_resolved: bool = False,
    ) -> list[dict[str, Any]]:
        """Return graph-backed contradiction review items with stable IDs."""
        items = self._graph_contradictions(db_path)
        if not include_resolved:
            items = [item for item in items if item.unresolved]
        return [self._contradiction_to_dict(item) for item in items]

    def resolve_contradiction(
        self,
        db_path: Path | str,
        *,
        conflict_id: str,
        resolution: str,
        note: Optional[str] = None,
        reviewer: Optional[str] = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Update review metadata for one conflict without mutating evidence values."""
        if resolution not in _CONFLICT_RESOLUTION_STATUSES:
            allowed = ", ".join(sorted(_CONFLICT_RESOLUTION_STATUSES))
            raise ValueError(f"Unsupported resolution {resolution!r}; expected one of: {allowed}")

        from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph

        db = Path(db_path).expanduser()
        kg = KnowledgeGraph(str(db))
        try:
            rows = kg.conn.execute("SELECT * FROM entities ORDER BY type, name, id").fetchall()
            for row in rows:
                properties = json.loads(row["properties"] or "{}")
                conflicts = properties.get("conflicts")
                if not conflicts:
                    continue
                entity = IngestEntity(
                    id=row["id"],
                    label=row["name"],
                    type=row["type"],
                    source_file=str(properties.get("source_file") or "graph://unknown"),
                    properties={**properties, "scope_id": row["scope_id"], "source_channel": row["source_channel"]},
                )
                updated_conflicts, before = self._resolve_conflict_in_properties(
                    entity,
                    conflicts,
                    conflict_id=conflict_id,
                    resolution=resolution,
                    note=note,
                    reviewer=reviewer,
                )
                if before is None:
                    continue

                after = self._contradiction_to_dict(self._normalize_conflicts(IngestEntity(
                    id=entity.id,
                    label=entity.label,
                    type=entity.type,
                    source_file=entity.source_file,
                    properties={**properties, "conflicts": updated_conflicts},
                ))[0])
                # Recompute the exact post-update item by ID because the entity may
                # contain multiple conflicts.
                for item in self._normalize_conflicts(IngestEntity(
                    id=entity.id,
                    label=entity.label,
                    type=entity.type,
                    source_file=entity.source_file,
                    properties={**properties, "conflicts": updated_conflicts},
                )):
                    if item.conflict_id == conflict_id:
                        after = self._contradiction_to_dict(item)
                        break

                if not dry_run:
                    properties["conflicts"] = updated_conflicts
                    kg.update_entity(Entity(
                        id=row["id"],
                        type=row["type"],
                        name=row["name"],
                        properties=properties,
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                        version=row["version"],
                        scope_id=row["scope_id"],
                        source_channel=row["source_channel"],
                    ), source_channel="wiki-review")

                return {
                    "ok": True,
                    "dry_run": dry_run,
                    "updated": not dry_run,
                    "conflict_id": conflict_id,
                    "entity_id": row["id"],
                    "resolution": resolution,
                    "before": before,
                    "after": after,
                    "rebuild_required": not dry_run,
                }
        finally:
            kg.close()

        raise KeyError(f"Conflict not found: {conflict_id}")

    def rebuild_from_graph(
        self,
        db_path: Path | str,
        *,
        dry_run: bool = False,
    ) -> WikiUpdate:
        """Regenerate generated sections from graph rows while preserving notes."""
        from mnemosyne.graph.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph(str(Path(db_path).expanduser()))
        try:
            entities = self._graph_entities(kg)
            relations = self._graph_relations(kg)
        finally:
            kg.close()

        by_source: dict[str, list[IngestEntity]] = {}
        for entity in entities:
            sources = entity.properties.get("source_files") or [entity.properties.get("source_file")]
            for source in sources:
                if source:
                    by_source.setdefault(str(source), []).append(entity)
        if not by_source and entities:
            by_source["graph://rebuild"] = entities

        touched: list[Path] = []
        if dry_run:
            planned = [self._source_page_path(src, self._domain_for_entities(items)) for src, items in by_source.items()]
            planned.extend(self._entity_path(entity) for entity in entities)
            planned.append(self.wiki_root / "index.md")
            return WikiUpdate(paths=self._dedupe_paths(planned))

        with self.write_lock("rebuild_from_graph"):
            for source, items in sorted(by_source.items()):
                item_ids = {item.id for item in items}
                parsed = ParsedIngestResult(
                    source_file=source,
                    domain=self._domain_for_entities(items),
                    entities=items,
                    relations=[r for r in relations if r.source in item_ids or r.target in item_ids],
                )
                raw_path = Path(source).expanduser() if not source.startswith(("text://", "graph://")) else None
                touched.extend(
                    self._update_from_ingest_unlocked(
                        parsed,
                        source=source,
                        domain=parsed.domain,
                        scope_id=self._common_scope(items),
                        source_channel=self._common_channel(items),
                        raw_path=raw_path if raw_path and raw_path.exists() else None,
                        content_hash=self._hash_file(raw_path) if raw_path and raw_path.exists() else None,
                        log_event=False,
                    ).paths
                )
            touched.append(self._write_index())
        return WikiUpdate(paths=self._dedupe_paths(touched))

    def _ensure_dirs(self) -> None:
        for rel in ("sources", "entities"):
            (self.wiki_root / rel).mkdir(parents=True, exist_ok=True)

    def _write_source_page(
        self,
        parsed: ParsedIngestResult,
        *,
        source: str,
        domain: str,
        scope_id: Optional[str],
        source_channel: str,
        raw_path: Optional[Path],
        original_source: str,
        content_hash: Optional[str],
    ) -> Path:
        path = self._source_page_path(source or parsed.source_file or "inline-text", domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        title = self._source_title(source or parsed.source_file or path.stem)
        source_id = self._source_id(original_source or source)
        content_hash = content_hash or (self._hash_file(raw_path) if raw_path and raw_path.exists() else None)
        frontmatter = self._frontmatter({
            "page_type": "source",
            "domain": domain,
            "source_id": source_id,
            "source": source,
            "original_source": original_source,
            "raw_path": str(raw_path) if raw_path else "",
            "content_hash": content_hash or "",
            "scope_id": scope_id or "global",
            "source_channel": source_channel,
            "updated_at": self._now(),
        })
        lines = [
            frontmatter,
            f"# {title}",
            "",
            _GENERATED_START,
            "",
            *_EDITOR_GUIDANCE_LINES,
            "",
            "## Metadata",
            "",
            f"- **Domain**: {domain}",
            f"- **Source ID**: `{source_id}`",
            f"- **Source**: `{source}`",
            f"- **Original source**: `{original_source}`",
            f"- **Raw path**: `{raw_path}`" if raw_path else "- **Raw path**: _inline or unavailable_",
            f"- **Content hash**: `{content_hash}`" if content_hash else "- **Content hash**: _unavailable_",
            f"- **Scope**: {scope_id or 'global'}",
            f"- **Source channel**: {source_channel}",
            f"- **Updated**: {self._now()}",
            "",
            "## Extracted entities",
            "",
        ]
        if parsed.entities:
            for entity in sorted(parsed.entities, key=lambda e: (e.type, e.label, e.id)):
                lines.append(
                    f"- {self._entity_link(entity)} — `{entity.type}` "
                    f"(confidence: {entity.confidence}, {entity.confidence_score:g})"
                )
        else:
            lines.append("- _No entities extracted._")

        lines.extend(["", "## Extracted relations", ""])
        if parsed.relations:
            entity_by_id = {e.id: e for e in parsed.entities}
            for rel in sorted(parsed.relations, key=lambda r: (r.source, r.relation, r.target)):
                lines.append(f"- {self._relation_line(rel, entity_by_id)}")
        else:
            lines.append("- _No relations extracted._")

        excerpt = self._read_excerpt(raw_path) if self.include_excerpts else ""
        if excerpt:
            lines.extend(["", "## Source excerpt", "", "```text", excerpt, "```"])
        else:
            lines.extend(["", "## Source excerpt", "", "_Omitted by default. Use `--wiki-excerpts` to opt in._"])

        lines.extend(["", _GENERATED_END, "", "## Notes", ""])
        self._write_replace_generated(path, "\n".join(lines).rstrip() + "\n")
        return path

    def _write_entity_page(
        self,
        entity: IngestEntity,
        *,
        relations: list[IngestRelation],
        source_page: Path,
        scope_id: Optional[str],
        source_channel: str,
    ) -> Path:
        path = self._entity_path(entity)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        existing_sources = self._collect_bullets(existing, "## Sources")
        existing_relations = self._collect_bullets(existing, "## Relations")
        source_link = self._wiki_link_for_path(source_page)
        source_bullets = self._sorted_unique([*existing_sources, f"- {source_link}"])
        relation_bullets = self._sorted_unique([
            *existing_relations,
            *(f"- {self._relation_line(rel)}" for rel in relations),
        ])
        resolved_scope = scope_id or entity.properties.get("scope_id") or "global"
        frontmatter = self._frontmatter({
            "page_type": "entity",
            "entity_id": entity.id,
            "entity_type": entity.type,
            "label": entity.label,
            "scope_id": str(resolved_scope),
            "source_channel": source_channel,
            "updated_at": self._now(),
        })
        lines = [
            frontmatter,
            f"# {entity.label}",
            "",
            _GENERATED_START,
            "",
            *_EDITOR_GUIDANCE_LINES,
            "",
            "## Summary",
            "",
            f"- **Type**: `{entity.type}`",
            f"- **Entity ID**: `{entity.id}`",
            f"- **Scope**: {resolved_scope}",
            f"- **Source channel**: {source_channel}",
            f"- **Confidence**: {entity.confidence} ({entity.confidence_score:g})",
            f"- **Updated**: {self._now()}",
            "",
            "## Properties",
            "",
        ]
        lines.extend(self._property_lines(entity) or ["- _No additional properties._"])
        contradiction_lines = self._contradiction_section_lines(entity)
        if contradiction_lines:
            lines.extend(["", *contradiction_lines])
        lines.extend(["", "## Sources", "", *source_bullets])
        lines.extend(["", "## Relations", ""])
        lines.extend(relation_bullets or ["- _No relations recorded yet._"])
        lines.extend(["", _GENERATED_END, "", "## Notes", ""])
        self._write_replace_generated(path, "\n".join(lines).rstrip() + "\n")
        return path

    def _write_index(self) -> Path:
        path = self.wiki_root / "index.md"

        if _HAS_RUST_CORE:
            entity_files = mnemosyne_core.fast_glob_markdown(str(self.wiki_root / "entities"))
            source_files = mnemosyne_core.fast_glob_markdown(str(self.wiki_root / "sources"))
            entity_pages = [Path(p) for p in sorted(entity_files)]
            source_pages = [Path(p) for p in sorted(source_files)]
            
            content = mnemosyne_core.fast_rebuild_index(
                str(self.wiki_root),
                [str(p) for p in entity_pages],
                [str(p) for p in source_pages],
                self._now(),
                _EDITOR_GUIDANCE_LINES
            )
            self._write_replace_generated(path, content)
            return path

        entity_pages = sorted((self.wiki_root / "entities").glob("*/*.md"))
        source_pages = sorted((self.wiki_root / "sources").glob("*/*.md"))
        frontmatter = self._frontmatter({"page_type": "index", "updated_at": self._now()})
        lines = [
            frontmatter,
            "# Mnemosyne LLM Wiki Index",
            "",
            _GENERATED_START,
            "",
            *_EDITOR_GUIDANCE_LINES,
            "",
            f"Last updated: {self._now()}",
            "",
            "## Entity pages",
            "",
        ]
        lines.extend([f"- {self._wiki_link_for_path(page)}" for page in entity_pages] or ["- _No entity pages yet._"])
        lines.extend(["", "## Source pages", ""])
        lines.extend([f"- {self._wiki_link_for_path(page)}" for page in source_pages] or ["- _No source pages yet._"])
        lines.extend([
            "",
            "## Maintenance",
            "",
            "- [[log]] records ingest chronology." if (self.wiki_root / "log.md").exists() else "- Log page is created on first ingest event.",
            "- Knowledge graph queries remain available through `mnemosyne query`.",
            "- Raw sources remain outside this wiki and should be treated as source of truth.",
            "",
            _GENERATED_END,
            "",
        ])
        self._write_replace_generated(path, "\n".join(lines))
        return path

    def _append_log(self, *, source: str, domain: str, scope_id: Optional[str], source_channel: str, source_page: Path, entities: int, relations: int) -> Path:
        path = self.wiki_root / "log.md"
        if not path.exists():
            self._atomic_write(path, self._frontmatter({"page_type": "log", "updated_at": self._now()}) + "# Mnemosyne LLM Wiki Log\n\n")
        entry = "\n".join([
            f"## [{self._now()}] ingest | {self._source_title(source)}",
            "",
            f"- **Source page**: {self._wiki_link_for_path(source_page)}",
            f"- **Domain**: {domain}",
            f"- **Scope**: {scope_id or 'global'}",
            f"- **Source channel**: {source_channel}",
            f"- **Entities**: {entities}",
            f"- **Relations**: {relations}",
            "",
        ])
        with path.open("a", encoding="utf-8") as fh:
            fh.write(entry)
        return path

    @staticmethod
    def _relations_for_entity(entity_id: str, relations: Iterable[IngestRelation]) -> list[IngestRelation]:
        return [r for r in relations if r.source == entity_id or r.target == entity_id]

    def _relation_line(self, rel: IngestRelation, entity_by_id: Optional[dict[str, IngestEntity]] = None) -> str:
        if entity_by_id:
            source = self._entity_link(entity_by_id[rel.source]) if rel.source in entity_by_id else f"`{rel.source}`"
            target = self._entity_link(entity_by_id[rel.target]) if rel.target in entity_by_id else f"`{rel.target}`"
        else:
            source = f"`{rel.source}`"
            target = f"`{rel.target}`"
        return f"{source} --`{rel.relation}`--> {target}"

    def _entity_link(self, entity: IngestEntity) -> str:
        rel = self._entity_path(entity).relative_to(self.wiki_root).with_suffix("")
        return f"[[{rel.as_posix()}|{entity.label}]]"

    def _entity_path(self, entity: IngestEntity) -> Path:
        base = self.wiki_root / "entities" / self._slug(entity.type) / f"{self._slug(entity.label or entity.id)}.md"
        return self._disambiguate_page(base, "entity", entity.id)

    def _source_page_path(self, source: str, domain: str) -> Path:
        base = self.wiki_root / "sources" / domain / f"{self._source_slug(source)}.md"
        return self._disambiguate_page(base, "source", self._source_id(source))

    def _disambiguate_page(self, base: Path, page_type: str, identity: str) -> Path:
        if not base.exists():
            return base
        frontmatter = self._parse_frontmatter(base.read_text(encoding="utf-8"))
        existing = frontmatter.get("entity_id") if page_type == "entity" else frontmatter.get("source_id")
        if not existing or str(existing) == identity:
            return base
        return base.with_name(f"{base.stem}-{self._short_hash(identity)}{base.suffix}")

    def _wiki_link_for_path(self, path: Path) -> str:
        rel = path.relative_to(self.wiki_root).with_suffix("")
        return f"[[{rel.as_posix()}|{self._page_title(path)}]]"

    @staticmethod
    def _page_title(path: Path) -> str:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return path.stem.replace("-", " ").title()
        in_frontmatter = False
        for line in lines:
            if line == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue
            if line.startswith("# "):
                return line.removeprefix("# ").strip()
        return path.stem.replace("-", " ").title()

    @staticmethod
    def _source_title(source: str) -> str:
        if source.startswith("text://"):
            return source
        return source if source.startswith(("http://", "https://")) else (Path(source).name or source)

    @staticmethod
    def _source_slug(source: str) -> str:
        if source.startswith("text://"):
            return LLMWikiMaintainer._slug(source)
        if source.startswith(("http://", "https://")):
            source = source.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or source
        else:
            parsed = Path(source)
            source = parsed.stem or parsed.name or source
        return LLMWikiMaintainer._slug(source)

    @staticmethod
    def _source_id(source: str) -> str:
        return LLMWikiMaintainer._short_hash(source)

    @staticmethod
    def _slug(value: str) -> str:
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9가-힣._-]+", "-", value)
        return value.strip("-._") or "untitled"

    @staticmethod
    def _short_hash(value: str) -> str:
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _hash_file(path: Optional[Path]) -> Optional[str]:
        if path is None:
            return None
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _read_excerpt(raw_path: Optional[Path]) -> str:
        if raw_path is None or not raw_path.exists() or not raw_path.is_file():
            return ""
        try:
            text = raw_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        text = LLMWikiMaintainer._redact_sensitive_text(text)
        text = text.strip()
        return text[:_MAX_SOURCE_EXCERPT].rstrip() + ("\n..." if len(text) > _MAX_SOURCE_EXCERPT else "")

    @staticmethod
    def _redact_sensitive_text(text: str) -> str:
        for pattern, replacement in _SECRET_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    @staticmethod
    def _format_conflict_value(value: Any) -> str:
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except TypeError:
                text = str(value)
        text = LLMWikiMaintainer._redact_sensitive_text(text).replace("\n", "\\n")
        return text[:197].rstrip() + "..." if len(text) > 200 else text

    @staticmethod
    def _property_lines(entity: IngestEntity) -> list[str]:
        lines: list[str] = []
        for key, value in sorted(entity.properties.items()):
            if key in {"label", "conflicts"}:
                continue
            lines.append(f"- **{key}**: `{value}`")
        return lines

    @staticmethod
    def _normalize_conflicts(entity: IngestEntity) -> list[WikiContradiction]:
        raw_conflicts = entity.properties.get("conflicts")
        if not raw_conflicts:
            return []

        normalized: list[WikiContradiction] = []
        conflict_items: Iterable[tuple[Any, Any]]
        if isinstance(raw_conflicts, dict):
            conflict_items = raw_conflicts.items()
        elif isinstance(raw_conflicts, list):
            conflict_items = (("unknown", raw_conflicts),)
        else:
            return []

        for property_name, entries in conflict_items:
            if isinstance(entries, dict):
                entry_list: list[Any] = [entries]
            elif isinstance(entries, list):
                entry_list = entries
            else:
                entry_list = [entries]

            for entry in entry_list:
                normalized.append(LLMWikiMaintainer._normalize_conflict_entry(entity, property_name, entry))

        return sorted(
            normalized,
            key=lambda item: (
                item.entity_label,
                item.property_name,
                item.source_file,
                item.detected_at,
                item.resolution,
                LLMWikiMaintainer._format_conflict_value(item.incoming),
            ),
        )

    @staticmethod
    def _normalize_conflict_entry(entity: IngestEntity, property_name: Any, entry: Any) -> WikiContradiction:
        if isinstance(entry, dict):
            name = str(entry.get("property_name") or entry.get("property") or property_name or "unknown")
            existing = entry.get("existing")
            incoming = entry.get("incoming")
            source_file = str(entry.get("source_file") or entry.get("source") or "unknown")
            source_id_value = entry.get("source_id")
            detected_at = str(entry.get("detected_at") or entry.get("seen_at") or "unknown")
            resolution = str(entry.get("resolution") or "unresolved")
            reviewer = str(entry.get("reviewer") or "")
            review_note = str(entry.get("review_note") or entry.get("note") or "")
            reviewed_at = str(entry.get("reviewed_at") or "")
        else:
            name = str(property_name or "unknown")
            existing = entity.properties.get(name)
            incoming = entry
            source_file = "unknown"
            source_id_value = None
            detected_at = "unknown"
            resolution = "unresolved"
            reviewer = ""
            review_note = ""
            reviewed_at = ""

        if resolution not in _CONFLICT_RESOLUTION_STATUSES:
            resolution = "unresolved"
        source_id = str(source_id_value) if source_id_value else (
            "unknown" if source_file == "unknown" else LLMWikiMaintainer._source_id(source_file)
        )
        conflict_id = LLMWikiMaintainer._conflict_id(
            entity_id=entity.id,
            property_name=name,
            existing=existing,
            incoming=incoming,
            source_file=source_file,
            source_id=source_id,
            detected_at=detected_at,
        )
        return WikiContradiction(
            conflict_id=conflict_id,
            entity_id=entity.id,
            entity_label=entity.label,
            property_name=name,
            existing=existing,
            incoming=incoming,
            source_file=source_file,
            source_id=source_id,
            detected_at=detected_at,
            resolution=resolution,
            reviewer=reviewer,
            review_note=review_note,
            reviewed_at=reviewed_at,
        )

    @staticmethod
    def _conflict_id(
        *,
        entity_id: str,
        property_name: str,
        existing: Any,
        incoming: Any,
        source_file: str,
        source_id: str,
        detected_at: str,
    ) -> str:
        payload = {
            "entity_id": entity_id,
            "property_name": property_name,
            "existing": LLMWikiMaintainer._canonical_conflict_value(existing),
            "incoming": LLMWikiMaintainer._canonical_conflict_value(incoming),
            "source_file": source_file,
            "source_id": source_id,
            "detected_at": detected_at,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"c_{LLMWikiMaintainer._short_hash(encoded)}"

    @staticmethod
    def _canonical_conflict_value(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)

    @staticmethod
    def _contradiction_to_dict(item: WikiContradiction) -> dict[str, Any]:
        return {
            "conflict_id": item.conflict_id,
            "entity_id": item.entity_id,
            "entity_label": item.entity_label,
            "property_name": item.property_name,
            "existing": LLMWikiMaintainer._format_conflict_value(item.existing),
            "incoming": LLMWikiMaintainer._format_conflict_value(item.incoming),
            "source_file": item.source_file,
            "source_id": item.source_id,
            "detected_at": item.detected_at,
            "resolution": item.resolution,
            "reviewer": item.reviewer,
            "review_note": item.review_note,
            "reviewed_at": item.reviewed_at,
        }

    @staticmethod
    def _resolve_conflict_in_properties(
        entity: IngestEntity,
        conflicts: Any,
        *,
        conflict_id: str,
        resolution: str,
        note: Optional[str],
        reviewer: Optional[str],
    ) -> tuple[Any, Optional[dict[str, Any]]]:
        if not isinstance(conflicts, dict):
            return conflicts, None

        updated: dict[Any, Any] = {}
        before: Optional[dict[str, Any]] = None
        reviewed_at = LLMWikiMaintainer._now()
        for property_name, entries in conflicts.items():
            if isinstance(entries, list):
                new_entries: list[Any] = []
                for entry in entries:
                    item = LLMWikiMaintainer._normalize_conflict_entry(entity, property_name, entry)
                    if item.conflict_id != conflict_id:
                        new_entries.append(entry)
                        continue
                    before = LLMWikiMaintainer._contradiction_to_dict(item)
                    mutable = dict(entry) if isinstance(entry, dict) else {
                        "existing": item.existing,
                        "incoming": item.incoming,
                        "source_file": item.source_file,
                        "source_id": item.source_id,
                        "detected_at": item.detected_at,
                    }
                    mutable["resolution"] = resolution
                    mutable["reviewed_at"] = reviewed_at
                    if note is not None:
                        mutable["review_note"] = note
                    if reviewer is not None:
                        mutable["reviewer"] = reviewer
                    new_entries.append(mutable)
                updated[property_name] = new_entries
            else:
                item = LLMWikiMaintainer._normalize_conflict_entry(entity, property_name, entries)
                if item.conflict_id != conflict_id:
                    updated[property_name] = entries
                    continue
                before = LLMWikiMaintainer._contradiction_to_dict(item)
                mutable = dict(entries) if isinstance(entries, dict) else {
                    "existing": item.existing,
                    "incoming": item.incoming,
                    "source_file": item.source_file,
                    "source_id": item.source_id,
                    "detected_at": item.detected_at,
                }
                mutable["resolution"] = resolution
                mutable["reviewed_at"] = reviewed_at
                if note is not None:
                    mutable["review_note"] = note
                if reviewer is not None:
                    mutable["reviewer"] = reviewer
                updated[property_name] = mutable

        return updated, before

    @staticmethod
    def _contradiction_section_lines(entity: IngestEntity) -> list[str]:
        unresolved = [item for item in LLMWikiMaintainer._normalize_conflicts(entity) if item.unresolved]
        if not unresolved:
            return []

        lines = [
            "## Potential contradictions",
            "",
            "_Needs review: generated deterministically from conflict metadata; this is not an LLM semantic truth judgment._",
            "",
        ]
        for item in unresolved:
            existing = LLMWikiMaintainer._format_conflict_value(item.existing)
            incoming = LLMWikiMaintainer._format_conflict_value(item.incoming)
            lines.append(
                f"- **Needs review** `{item.conflict_id}`: `{item.property_name}` has conflicting values; "
                f"existing `{existing}` vs incoming `{incoming}`. "
                f"Source: `{item.source_file}` (`{item.source_id}`); "
                f"detected: `{item.detected_at}`; resolution: `{item.resolution}`."
            )
        return lines

    @staticmethod
    def _frontmatter(values: dict[str, Any]) -> str:
        lines = ["---"]
        for key, value in values.items():
            if value is None:
                value = ""
            encoded = json.dumps(value, ensure_ascii=False) if not isinstance(value, (int, float)) else str(value)
            lines.append(f"{key}: {encoded}")
        lines.extend(["---", ""])
        return "\n".join(lines)

    @staticmethod
    def _parse_frontmatter(text: str) -> dict[str, str]:
        if not text.startswith("---\n"):
            return {}
        end = text.find("\n---", 4)
        if end == -1:
            return {}
        out: dict[str, str] = {}
        for line in text[4:end].splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = value.strip('"')
            out[key.strip()] = str(parsed)
        return out

    @staticmethod
    def _write_replace_generated(path: Path, content: str) -> None:
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if _GENERATED_START in existing and _GENERATED_END in existing:
                end = existing.index(_GENERATED_END) + len(_GENERATED_END)
                new_start = content.index(_GENERATED_START)
                new_end = content.index(_GENERATED_END) + len(_GENERATED_END)
                old_frontmatter_end = LLMWikiMaintainer._frontmatter_end(existing)
                new_frontmatter_end = LLMWikiMaintainer._frontmatter_end(content)
                prefix = content[:new_frontmatter_end] if new_frontmatter_end else existing[:old_frontmatter_end]
                title_block = content[new_frontmatter_end:new_start]
                suffix = existing[end:]
                content = prefix + title_block + content[new_start:new_end] + suffix
        LLMWikiMaintainer._atomic_write(path, content)

    @staticmethod
    def _frontmatter_end(text: str) -> int:
        if not text.startswith("---\n"):
            return 0
        end = text.find("\n---", 4)
        return end + len("\n---\n") if end != -1 else 0

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @staticmethod
    def _collect_bullets(markdown: str, heading: str) -> list[str]:
        if heading not in markdown:
            return []
        section = markdown.split(heading, 1)[1]
        next_heading = re.search(r"\n## ", section)
        if next_heading:
            section = section[: next_heading.start()]
        return [line.rstrip() for line in section.splitlines() if line.startswith("- ")]

    @staticmethod
    def _sorted_unique(items: Iterable[str]) -> list[str]:
        return sorted({item for item in items if item.strip() and not item.startswith("- _No ")})

    @staticmethod
    def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
        out: list[Path] = []
        seen: set[Path] = set()
        for path in paths:
            if path not in seen:
                out.append(path)
                seen.add(path)
        return out

    @staticmethod
    def _extract_wiki_links(text: str) -> list[str]:
        return re.findall(r"\[\[([^\]]+)\]\]", text)

    def _last_log_entry(self) -> Optional[str]:
        log = self.wiki_root / "log.md"
        if not log.exists():
            return None
        for line in reversed(log.read_text(encoding="utf-8").splitlines()):
            if line.startswith("## ["):
                return line
        return None

    def _requires_frontmatter(self, page: Path) -> bool:
        try:
            rel = page.relative_to(self.wiki_root)
        except ValueError:
            return False
        return rel.parts[:1] in [("entities",), ("sources",)] or page.name in {"index.md", "log.md"}

    def _add_graph_drift_warnings(self, db_path: Optional[Path | str], warnings: list[WikiLintIssue]) -> None:
        if db_path is None or not Path(db_path).expanduser().exists():
            return
        from mnemosyne.graph.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph(str(Path(db_path).expanduser()))
        try:
            stats = kg.get_stats()
        finally:
            kg.close()
        entity_pages = len(list((self.wiki_root / "entities").glob("*/*.md")))
        if stats.get("entities", 0) and entity_pages < int(stats["entities"]):
            warnings.append(WikiLintIssue("warning", "graph-wiki-count-mismatch", str(self.wiki_root), "Graph has more entities than wiki entity pages"))

    def _add_contradiction_warnings(self, db_path: Optional[Path | str], warnings: list[WikiLintIssue]) -> None:
        for item in self._graph_contradictions(db_path):
            if not item.unresolved:
                continue
            warnings.append(WikiLintIssue(
                "warning",
                "unresolved-contradiction",
                f"entity:{item.entity_id}",
                (
                    f"Potential contradiction needs review for {item.entity_label} "
                    f"property {item.property_name!r}; source={item.source_file}; "
                    "generated from conflict metadata only"
                ),
            ))

    def _add_stale_warnings(self, db_path: Optional[Path | str], warnings: list[WikiLintIssue]) -> None:
        if db_path is None:
            return
        for item in self._stale_candidates(db_path):
            warnings.append(WikiLintIssue(
                "warning",
                "stale-candidate",
                item.path or item.entity_id or item.source_id or str(self.wiki_root),
                f"{item.kind}: {item.reason}; risk={item.risk}; action={item.recommended_action}",
            ))

    def _contradiction_stats(self, db_path: Optional[Path | str]) -> dict[str, Any]:
        contradictions = self._graph_contradictions(db_path)
        by_entity: dict[str, dict[str, Any]] = {}
        resolution_counts = {status: 0 for status in sorted(_CONFLICT_RESOLUTION_STATUSES)}
        for item in contradictions:
            resolution_counts[item.resolution] = resolution_counts.get(item.resolution, 0) + 1
            entity_stats = by_entity.setdefault(item.entity_id, {
                "label": item.entity_label,
                "total": 0,
                "unresolved": 0,
                "resolved": 0,
            })
            entity_stats["total"] += 1
            if item.unresolved:
                entity_stats["unresolved"] += 1
            else:
                entity_stats["resolved"] += 1

        unresolved = resolution_counts.get("unresolved", 0)
        total = len(contradictions)
        return {
            "total": total,
            "unresolved": unresolved,
            "resolved": total - unresolved,
            "resolution_counts": resolution_counts,
            "by_entity": dict(sorted(by_entity.items())),
        }

    def _graph_contradictions(self, db_path: Optional[Path | str]) -> list[WikiContradiction]:
        if db_path is None or not Path(db_path).expanduser().exists():
            return []
        from mnemosyne.graph.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph(str(Path(db_path).expanduser()))
        try:
            entities = self._graph_entities(kg)
        finally:
            kg.close()

        contradictions: list[WikiContradiction] = []
        for entity in entities:
            contradictions.extend(self._normalize_conflicts(entity))
        return sorted(
            contradictions,
            key=lambda item: (
                item.entity_label,
                item.property_name,
                item.source_file,
                item.detected_at,
                item.resolution,
            ),
        )

    def _stale_stats(self, db_path: Optional[Path | str]) -> dict[str, Any]:
        candidates = self._stale_candidates(db_path) if db_path is not None else []
        by_kind: dict[str, int] = {}
        by_risk: dict[str, int] = {}
        for candidate in candidates:
            by_kind[candidate.kind] = by_kind.get(candidate.kind, 0) + 1
            by_risk[candidate.risk] = by_risk.get(candidate.risk, 0) + 1
        return {
            "total": len(candidates),
            "by_kind": dict(sorted(by_kind.items())),
            "by_risk": dict(sorted(by_risk.items())),
        }

    def _stale_candidates(self, db_path: Optional[Path | str]) -> list[WikiStaleCandidate]:
        if db_path is None or not Path(db_path).expanduser().exists() or not self.wiki_root.exists():
            return []

        from mnemosyne.graph.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph(str(Path(db_path).expanduser()))
        try:
            entities = self._graph_entities(kg)
        finally:
            kg.close()

        graph_entity_ids = {entity.id for entity in entities}
        graph_source_ids: set[str] = set()
        graph_local_sources_by_entity: list[tuple[IngestEntity, str]] = []
        for entity in entities:
            sources = entity.properties.get("source_files") or [entity.properties.get("source_file") or entity.source_file]
            for source in sources:
                if not source:
                    continue
                source_str = str(source)
                graph_source_ids.add(self._source_id(source_str))
                if self._is_local_source_path(source_str) and not Path(source_str).expanduser().exists():
                    graph_local_sources_by_entity.append((entity, source_str))

        candidates: list[WikiStaleCandidate] = []
        for page in sorted((self.wiki_root / "entities").glob("*/*.md")):
            frontmatter = self._parse_frontmatter(page.read_text(encoding="utf-8"))
            entity_id = str(frontmatter.get("entity_id") or "")
            if entity_id and entity_id not in graph_entity_ids:
                candidates.append(self._make_stale_candidate(
                    kind="stale-wiki-entity-page",
                    reason="entity page identity is no longer present in the graph database",
                    risk="high",
                    path=page,
                    entity_id=entity_id,
                    recommended_action="write tombstone before any manual cleanup",
                ))

        for page in sorted((self.wiki_root / "sources").glob("*/*.md")):
            text = page.read_text(encoding="utf-8")
            frontmatter = self._parse_frontmatter(text)
            source_id = str(frontmatter.get("source_id") or "")
            source = str(frontmatter.get("source") or frontmatter.get("original_source") or "")
            raw_path = str(frontmatter.get("raw_path") or "")
            if source_id and source_id not in graph_source_ids:
                candidates.append(self._make_stale_candidate(
                    kind="stale-wiki-source-page",
                    reason="source page identity is no longer referenced by graph entity source metadata",
                    risk="high",
                    path=page,
                    source_id=source_id,
                    source=source,
                    recommended_action="write tombstone before any manual cleanup",
                ))
            if raw_path and self._is_local_source_path(raw_path) and not Path(raw_path).expanduser().exists():
                candidates.append(self._make_stale_candidate(
                    kind="missing-raw-source",
                    reason="source page raw_path no longer exists on disk; this does not imply the graph fact is false",
                    risk="medium",
                    path=page,
                    source_id=source_id,
                    source=raw_path,
                    recommended_action="review source lifecycle and keep page unless intentionally archived",
                ))

        for entity, source in graph_local_sources_by_entity:
            candidates.append(self._make_stale_candidate(
                kind="graph-entity-missing-source",
                reason="graph entity source_file/source_files entry no longer exists on disk; fact is retained for review",
                risk="medium",
                entity_id=entity.id,
                source=source,
                recommended_action="review upstream source lifecycle before changing graph facts",
            ))

        return sorted(
            self._dedupe_stale_candidates(candidates),
            key=lambda item: (item.risk, item.kind, item.path, item.entity_id, item.source_id, item.source),
        )

    def _make_stale_candidate(
        self,
        *,
        kind: str,
        reason: str,
        risk: str,
        path: Optional[Path] = None,
        entity_id: str = "",
        source_id: str = "",
        source: str = "",
        recommended_action: str,
    ) -> WikiStaleCandidate:
        rel_path = ""
        manual_note_preview = ""
        if path is not None:
            try:
                rel_path = path.relative_to(self.wiki_root).as_posix()
            except ValueError:
                rel_path = str(path)
            manual_note_preview = self._manual_note_preview(path)
        candidate_id = self._stale_candidate_id(
            kind=kind,
            path=rel_path,
            entity_id=entity_id,
            source_id=source_id,
            source=source,
            reason=reason,
        )
        return WikiStaleCandidate(
            candidate_id=candidate_id,
            kind=kind,
            reason=reason,
            risk=risk,
            path=rel_path,
            entity_id=entity_id,
            source_id=source_id,
            source=source,
            manual_note_preview=manual_note_preview,
            recommended_action=recommended_action,
        )

    @staticmethod
    def _dedupe_stale_candidates(candidates: Iterable[WikiStaleCandidate]) -> list[WikiStaleCandidate]:
        out: list[WikiStaleCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.candidate_id in seen:
                continue
            out.append(candidate)
            seen.add(candidate.candidate_id)
        return out

    @staticmethod
    def _stale_candidate_id(
        *,
        kind: str,
        path: str,
        entity_id: str,
        source_id: str,
        source: str,
        reason: str,
    ) -> str:
        payload = json.dumps({
            "kind": kind,
            "path": path,
            "entity_id": entity_id,
            "source_id": source_id,
            "source": source,
            "reason": reason,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"stale_{LLMWikiMaintainer._short_hash(payload)}"

    @staticmethod
    def _is_local_source_path(source: str) -> bool:
        return bool(source) and not source.startswith(("text://", "graph://", "http://", "https://"))

    def _manual_note_preview(self, path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return ""
        notes = self._manual_notes(text).strip()
        notes = self._redact_sensitive_text(notes).replace("[[", "[ [")
        return notes[:497].rstrip() + "..." if len(notes) > 500 else notes

    @staticmethod
    def _manual_notes(text: str) -> str:
        if _GENERATED_END not in text:
            return ""
        suffix = text.split(_GENERATED_END, 1)[1].strip()
        return suffix

    @staticmethod
    def _stale_candidate_to_dict(candidate: WikiStaleCandidate) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "kind": candidate.kind,
            "reason": candidate.reason,
            "risk": candidate.risk,
            "path": candidate.path,
            "entity_id": candidate.entity_id,
            "source_id": candidate.source_id,
            "source": candidate.source,
            "manual_note_preview": candidate.manual_note_preview,
            "recommended_action": candidate.recommended_action,
        }

    def _stale_plan_payload(
        self,
        candidates: list[WikiStaleCandidate],
        *,
        dry_run: bool,
        tombstone_paths: list[str],
    ) -> dict[str, Any]:
        risk_counts: dict[str, int] = {}
        kind_counts: dict[str, int] = {}
        for candidate in candidates:
            risk_counts[candidate.risk] = risk_counts.get(candidate.risk, 0) + 1
            kind_counts[candidate.kind] = kind_counts.get(candidate.kind, 0) + 1
        return {
            "wiki_root": str(self.wiki_root),
            "generated_at": self._now(),
            "dry_run": dry_run,
            "deletes_performed": 0,
            "tombstones_written": len(tombstone_paths),
            "tombstone_paths": tombstone_paths,
            "count": len(candidates),
            "risk_counts": dict(sorted(risk_counts.items())),
            "kind_counts": dict(sorted(kind_counts.items())),
            "candidates": [self._stale_candidate_to_dict(candidate) for candidate in candidates],
        }

    def _write_tombstone(self, candidate: WikiStaleCandidate) -> Path:
        path = self.wiki_root / "tombstones" / f"{candidate.candidate_id}.md"
        frontmatter = self._frontmatter({
            "page_type": "tombstone",
            "candidate_id": candidate.candidate_id,
            "kind": candidate.kind,
            "risk": candidate.risk,
            "original_path": candidate.path,
            "entity_id": candidate.entity_id,
            "source_id": candidate.source_id,
            "source": candidate.source,
            "created_at": self._now(),
        })
        lines = [
            frontmatter,
            f"# Tombstone: {candidate.candidate_id}",
            "",
            _GENERATED_START,
            "",
            "## Stale candidate",
            "",
            f"- **Kind**: `{candidate.kind}`",
            f"- **Risk**: `{candidate.risk}`",
            f"- **Reason**: {candidate.reason}",
            f"- **Original path**: `{candidate.path or 'n/a'}`",
            f"- **Entity ID**: `{candidate.entity_id or 'n/a'}`",
            f"- **Source ID**: `{candidate.source_id or 'n/a'}`",
            f"- **Source**: `{candidate.source or 'n/a'}`",
            "- **Deletes performed**: `0`",
            "- **Recommended action**: " + candidate.recommended_action,
            "",
            "## Manual note recovery preview",
            "",
            "```text",
            candidate.manual_note_preview or "_No manual notes detected outside generated markers._",
            "```",
            "",
            _GENERATED_END,
            "",
        ]
        self._write_replace_generated(path, "\n".join(lines).rstrip() + "\n")
        return path

    def _semantic_candidates(
        self,
        db_path: Path | str,
        *,
        include_raw_excerpts: bool,
    ) -> list[WikiSemanticContradictionCandidate]:
        if not Path(db_path).expanduser().exists():
            return []

        from mnemosyne.graph.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph(str(Path(db_path).expanduser()))
        try:
            entities = self._graph_entities(kg)
        finally:
            kg.close()

        grouped: dict[tuple[str, str], list[IngestEntity]] = {}
        for entity in entities:
            key = (self._semantic_key(entity.label), self._semantic_key(entity.type))
            grouped.setdefault(key, []).append(entity)

        candidates: list[WikiSemanticContradictionCandidate] = []
        generated_at = self._now()
        for (_label_key, _type_key), items in sorted(grouped.items()):
            if len(items) < 2:
                continue
            for claim_type, property_names in (
                ("status", _STATUS_PROPERTIES),
                ("date", _DATE_PROPERTIES),
                ("responsibility", _RESPONSIBILITY_PROPERTIES),
            ):
                candidates.extend(
                    self._semantic_pair_candidates(
                        items,
                        claim_type=claim_type,
                        property_names=property_names,
                        generated_at=generated_at,
                        include_raw_excerpts=include_raw_excerpts,
                    )
                )
        return sorted(
            self._dedupe_semantic_candidates(candidates),
            key=lambda item: (item.subject_label, item.claim_type, -item.confidence, item.candidate_id),
        )

    def _semantic_pair_candidates(
        self,
        entities: list[IngestEntity],
        *,
        claim_type: str,
        property_names: set[str],
        generated_at: str,
        include_raw_excerpts: bool,
    ) -> list[WikiSemanticContradictionCandidate]:
        candidates: list[WikiSemanticContradictionCandidate] = []
        for left_index, left in enumerate(entities):
            for right in entities[left_index + 1:]:
                for left_prop, left_value in self._semantic_claims(left, property_names):
                    for right_prop, right_value in self._semantic_claims(right, property_names):
                        verdict = self._semantic_pair_verdict(
                            claim_type,
                            left_value=left_value,
                            right_value=right_value,
                        )
                        if verdict is None:
                            continue
                        confidence, uncertainty, rationale = verdict
                        evidence = [
                            self._semantic_evidence(
                                left,
                                property_name=left_prop,
                                value=left_value,
                                include_raw_excerpts=include_raw_excerpts,
                            ),
                            self._semantic_evidence(
                                right,
                                property_name=right_prop,
                                value=right_value,
                                include_raw_excerpts=include_raw_excerpts,
                            ),
                        ]
                        candidate_id = self._semantic_candidate_id(
                            subject_label=left.label,
                            subject_type=left.type,
                            claim_type=claim_type,
                            evidence=evidence,
                        )
                        candidates.append(WikiSemanticContradictionCandidate(
                            candidate_id=candidate_id,
                            subject_label=left.label,
                            subject_type=left.type,
                            claim_type=claim_type,
                            detector="local-heuristic-v1",
                            processing_mode="local-offline",
                            confidence=confidence,
                            uncertainty=uncertainty,
                            rationale=rationale,
                            evidence=evidence,
                            generated_at=generated_at,
                        ))
        return candidates

    @staticmethod
    def _semantic_claims(entity: IngestEntity, property_names: set[str]) -> list[tuple[str, Any]]:
        claims: list[tuple[str, Any]] = []
        for key, value in entity.properties.items():
            if key in {"conflicts", "source_file", "source_files", "source_channel", "scope_id"}:
                continue
            if LLMWikiMaintainer._semantic_key(key) in property_names and value not in (None, ""):
                claims.append((key, value))
        return claims

    @staticmethod
    def _semantic_pair_verdict(
        claim_type: str,
        *,
        left_value: Any,
        right_value: Any,
    ) -> Optional[tuple[float, str, str]]:
        left = LLMWikiMaintainer._semantic_value(left_value)
        right = LLMWikiMaintainer._semantic_value(right_value)
        if not left or not right or left == right:
            return None

        if claim_type == "status":
            pair = frozenset((left, right))
            if pair not in _STATUS_CONTRADICTION_PAIRS:
                return None
            return (
                0.78,
                "review candidate only; rule matched incompatible status words",
                "Two same-subject records contain status words that are usually mutually exclusive.",
            )
        if claim_type == "date":
            if not LLMWikiMaintainer._looks_like_date(left) or not LLMWikiMaintainer._looks_like_date(right):
                return None
            return (
                0.56,
                "low confidence; dates may refer to different events or revisions",
                "Two same-subject records use the same date-like property with different values.",
            )
        if claim_type == "responsibility":
            return (
                0.52,
                "low confidence; multiple owners or roles may be valid",
                "Two same-subject records assign different responsibility-like values.",
            )
        return None

    def _semantic_evidence(
        self,
        entity: IngestEntity,
        *,
        property_name: str,
        value: Any,
        include_raw_excerpts: bool,
    ) -> WikiSemanticEvidence:
        raw_excerpt = (
            self._semantic_raw_excerpt(entity.source_file, value)
            if include_raw_excerpts
            else ""
        )
        return WikiSemanticEvidence(
            entity_id=entity.id,
            entity_label=entity.label,
            entity_type=entity.type,
            source_file=entity.source_file,
            source_id=self._source_id(entity.source_file),
            property_name=property_name,
            excerpt=raw_excerpt or self._semantic_excerpt(value),
            excerpt_kind="raw-source-redacted" if raw_excerpt else "property-value-redacted",
        )

    @staticmethod
    def _semantic_key(value: Any) -> str:
        return re.sub(r"[^a-z0-9_]+", "_", str(value).strip().lower()).strip("_")

    @staticmethod
    def _semantic_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return re.sub(r"\s+", " ", str(value).strip().lower())

    @staticmethod
    def _looks_like_date(value: str) -> bool:
        return bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", value))

    @staticmethod
    def _semantic_excerpt(value: Any) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(value)
        text = LLMWikiMaintainer._redact_sensitive_text(text).strip()
        return text[:237].rstrip() + "..." if len(text) > 240 else text

    @staticmethod
    def _semantic_raw_excerpt(source_file: str, value: Any) -> str:
        if not LLMWikiMaintainer._is_local_source_path(source_file):
            return ""
        path = Path(source_file).expanduser()
        if not path.exists() or not path.is_file():
            return ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        text = LLMWikiMaintainer._redact_sensitive_text(text)
        needle = str(value).strip()
        if needle:
            index = text.lower().find(needle.lower())
            if index >= 0:
                start = max(0, index - 120)
                end = min(len(text), index + len(needle) + 120)
                text = text[start:end]
        text = re.sub(r"\s+", " ", text).strip()
        return text[:297].rstrip() + "..." if len(text) > 300 else text

    @staticmethod
    def _semantic_candidate_id(
        *,
        subject_label: str,
        subject_type: str,
        claim_type: str,
        evidence: list[WikiSemanticEvidence],
    ) -> str:
        payload = {
            "subject_label": subject_label,
            "subject_type": subject_type,
            "claim_type": claim_type,
            "evidence": [
                {
                    "entity_id": item.entity_id,
                    "property_name": item.property_name,
                    "excerpt": item.excerpt,
                }
                for item in evidence
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"sem_{LLMWikiMaintainer._short_hash(encoded)}"

    @staticmethod
    def _dedupe_semantic_candidates(
        candidates: Iterable[WikiSemanticContradictionCandidate],
    ) -> list[WikiSemanticContradictionCandidate]:
        out: list[WikiSemanticContradictionCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.candidate_id in seen:
                continue
            out.append(candidate)
            seen.add(candidate.candidate_id)
        return out

    def _semantic_payload(
        self,
        candidates: list[WikiSemanticContradictionCandidate],
        *,
        persisted: bool,
    ) -> dict[str, Any]:
        by_claim_type: dict[str, int] = {}
        for candidate in candidates:
            by_claim_type[candidate.claim_type] = by_claim_type.get(candidate.claim_type, 0) + 1
        return {
            "schema": _SEMANTIC_REVIEW_SCHEMA,
            "wiki_root": str(self.wiki_root),
            "generated_at": self._now(),
            "processing_mode": "local-offline",
            "remote_model": False,
            "detector": "local-heuristic-v1",
            "candidate_wording": "review candidates only; not truth judgments",
            "excerpt_policy": "redacted bounded property excerpts; raw source excerpts only with explicit opt-in",
            "persisted": persisted,
            "paths": [],
            "count": len(candidates),
            "open_count": sum(1 for item in candidates if item.status in _SEMANTIC_REVIEW_STATUS_OPEN),
            "by_claim_type": dict(sorted(by_claim_type.items())),
            "candidates": [self._semantic_candidate_to_dict(item) for item in candidates],
        }

    def _empty_semantic_payload(self, *, persisted: bool) -> dict[str, Any]:
        return {
            "schema": _SEMANTIC_REVIEW_SCHEMA,
            "wiki_root": str(self.wiki_root),
            "generated_at": "",
            "processing_mode": "not-run",
            "remote_model": False,
            "detector": "none",
            "candidate_wording": "semantic discovery has not been run",
            "excerpt_policy": "n/a",
            "persisted": persisted,
            "paths": [],
            "count": 0,
            "open_count": 0,
            "by_claim_type": {},
            "candidates": [],
        }

    @staticmethod
    def _semantic_candidate_to_dict(
        candidate: WikiSemanticContradictionCandidate,
    ) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "subject_label": candidate.subject_label,
            "subject_type": candidate.subject_type,
            "claim_type": candidate.claim_type,
            "detector": candidate.detector,
            "processing_mode": candidate.processing_mode,
            "remote_model": candidate.remote_model,
            "confidence": candidate.confidence,
            "uncertainty": candidate.uncertainty,
            "rationale": candidate.rationale,
            "generated_at": candidate.generated_at,
            "status": candidate.status,
            "evidence": [item.__dict__ for item in candidate.evidence],
        }

    def _semantic_candidates_json_path(self) -> Path:
        return self.wiki_root / "review" / "semantic-contradictions.json"

    def _semantic_candidates_page_path(self) -> Path:
        return self.wiki_root / "review" / "semantic-contradictions.md"

    def _write_semantic_candidates_json(self, payload: dict[str, Any]) -> Path:
        path = self._semantic_candidates_json_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(payload)
        payload["persisted"] = True
        payload["paths"] = [str(path), str(self._semantic_candidates_page_path())]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _write_semantic_candidates_page(self, payload: dict[str, Any]) -> Path:
        path = self._semantic_candidates_page_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        frontmatter = self._frontmatter({
            "page_type": "semantic_contradiction_review",
            "schema": _SEMANTIC_REVIEW_SCHEMA,
            "processing_mode": payload.get("processing_mode", "local-offline"),
            "remote_model": False,
            "updated_at": self._now(),
        })
        lines = [
            frontmatter,
            "# Semantic contradiction review candidates",
            "",
            _GENERATED_START,
            "",
            "## Safety boundary",
            "",
            "- These are opt-in local heuristic review candidates, not truth judgments.",
            "- Deterministic graph conflict metadata remains separate from this review list.",
            "- No graph facts are merged, deleted, or resolved by this page.",
            "- Remote model calls are disabled for this implementation.",
            "",
            "## Summary",
            "",
            f"- **Schema**: `{_SEMANTIC_REVIEW_SCHEMA}`",
            f"- **Processing mode**: `{payload.get('processing_mode')}`",
            f"- **Remote model**: `{payload.get('remote_model')}`",
            f"- **Candidates**: `{payload.get('count')}`",
            "",
            "## Candidates",
            "",
        ]
        for item in payload.get("candidates") or []:
            lines.extend([
                f"### {item['candidate_id']}",
                "",
                f"- **Subject**: {item['subject_label']} (`{item['subject_type']}`)",
                f"- **Claim type**: `{item['claim_type']}`",
                f"- **Confidence**: `{item['confidence']}`",
                f"- **Uncertainty**: {item['uncertainty']}",
                f"- **Rationale**: {item['rationale']}",
                "- **Status**: candidate",
                "",
                "Evidence:",
            ])
            for evidence in item.get("evidence") or []:
                excerpt = str(evidence["excerpt"]).replace("`", "'").replace("[[", "[ [")
                lines.append(
                    f"- `{evidence['entity_id']}` `{evidence['property_name']}` "
                    f"source=`{evidence['source_file']}` "
                    f"excerpt=`{excerpt}`"
                )
            lines.append("")
        if not payload.get("candidates"):
            lines.append("- _No candidates detected._")
        lines.extend(["", _GENERATED_END, "", "## Review notes", ""])
        self._write_replace_generated(path, "\n".join(lines).rstrip() + "\n")
        return path

    def _semantic_stats(self) -> dict[str, Any]:
        payload = self.list_semantic_contradictions()
        return {
            "schema": payload.get("schema", _SEMANTIC_REVIEW_SCHEMA),
            "persisted": payload.get("persisted", False),
            "processing_mode": payload.get("processing_mode", "not-run"),
            "remote_model": payload.get("remote_model", False),
            "total": int(payload.get("count") or 0),
            "open": int(payload.get("open_count") or 0),
            "by_claim_type": payload.get("by_claim_type") or {},
        }

    def _add_semantic_warnings(self, warnings: list[WikiLintIssue]) -> None:
        payload = self.list_semantic_contradictions()
        for item in payload.get("candidates") or []:
            if str(item.get("status") or "candidate") not in _SEMANTIC_REVIEW_STATUS_OPEN:
                continue
            warnings.append(WikiLintIssue(
                "warning",
                "semantic-contradiction-candidate",
                f"semantic:{item.get('candidate_id')}",
                (
                    f"Semantic review candidate for {item.get('subject_label')} "
                    f"claim_type={item.get('claim_type')}; "
                    "local heuristic only, not a truth judgment"
                ),
            ))

    @staticmethod
    def _graph_entities(kg: Any) -> list[IngestEntity]:
        rows = kg.conn.execute("SELECT * FROM entities ORDER BY type, name, id").fetchall()
        entities: list[IngestEntity] = []
        for row in rows:
            props = json.loads(row["properties"] or "{}")
            entities.append(IngestEntity(
                id=row["id"],
                label=row["name"],
                type=row["type"],
                source_file=str(props.get("source_file") or "graph://unknown"),
                confidence=str(props.get("confidence") or "EXTRACTED"),
                confidence_score=float(props.get("confidence_score") or 1.0),
                properties={**props, "scope_id": row["scope_id"], "source_channel": row["source_channel"]},
            ))
        return entities

    @staticmethod
    def _graph_relations(kg: Any) -> list[IngestRelation]:
        rows = kg.conn.execute("SELECT * FROM relations ORDER BY source_id, relation_type, target_id").fetchall()
        out: list[IngestRelation] = []
        for row in rows:
            props = json.loads(row["properties"] or "{}")
            out.append(IngestRelation(
                source=row["source_id"],
                target=row["target_id"],
                relation=row["relation_type"],
                confidence=str(props.get("confidence") or "EXTRACTED"),
                confidence_score=float(props.get("confidence_score") or 1.0),
            ))
        return out

    @staticmethod
    def _domain_for_entities(entities: list[IngestEntity]) -> str:
        for entity in entities:
            domain = entity.properties.get("domain")
            if domain in {"coding", "daily", "legal"}:
                return str(domain)
            if entity.type in {"function", "class", "module", "api", "dependency"}:
                return "coding"
        return "daily"

    @staticmethod
    def _common_scope(entities: list[IngestEntity]) -> Optional[str]:
        scopes = {str(e.properties.get("scope_id")) for e in entities if e.properties.get("scope_id")}
        return scopes.pop() if len(scopes) == 1 else None

    @staticmethod
    def _common_channel(entities: list[IngestEntity]) -> str:
        channels = {str(e.properties.get("source_channel")) for e in entities if e.properties.get("source_channel")}
        return channels.pop() if len(channels) == 1 else "rebuild"
